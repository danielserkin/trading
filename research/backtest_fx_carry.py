#!/usr/bin/env python3
"""Walk-forward FX carry signals using lagged OECD/FRED rate observations."""

from __future__ import annotations

import argparse
import bisect
import csv
import io
import json
import random
import statistics
import subprocess
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import backtest_currency_strength_swing as swing


RATE_SERIES = {
    "USD": "IRSTCI01USM156N", "EUR": "IRSTCI01EZM156N", "GBP": "IRSTCI01GBM156N",
    "JPY": "IRSTCI01JPM156N", "CHF": "IRSTCI01CHM156N", "CAD": "IRSTCI01CAM156N",
    "AUD": "IRSTCI01AUM156N", "NZD": "IRSTCI01NZM156N",
}


@dataclass(frozen=True)
class Config:
    family: str
    lookback_days: int
    min_rate_gap: float
    stop_atr: float
    rr: float
    hold_bars: int
    cards: int
    schedule: str

    @property
    def min_strength(self) -> float:
        return 0.0

    @property
    def key(self) -> str:
        return (
            f"{self.family}|lb={self.lookback_days}d|carrygap={self.min_rate_gap:g}|stop={self.stop_atr:g}atr|"
            f"rr={self.rr:g}|hold={self.hold_bars}d|cards={self.cards}|{self.schedule}"
        )


def fetch_rate(series_id: str, cache_dir: Path) -> list[tuple[date, float]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{series_id}.csv"
    if path.exists():
        content = path.read_text()
    else:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        completed = subprocess.run(
            ["curl", "-L", "--fail", "--silent", "--show-error", url],
            check=True, capture_output=True, text=True, timeout=45,
        )
        content = completed.stdout
        path.write_text(content)
    output = []
    for row in csv.DictReader(io.StringIO(content)):
        try:
            output.append((date.fromisoformat(row["observation_date"]), float(row[series_id])))
        except (KeyError, TypeError, ValueError):
            continue
    return output


def known_rate(rows: list[tuple[date, float]], signal_day: date) -> float | None:
    # Monthly OECD series are released after the observation month. A fixed
    # 45-day lag is deliberately conservative and prevents revision/lookahead.
    cutoff = signal_day - timedelta(days=45)
    dates = [row[0] for row in rows]
    index = bisect.bisect_right(dates, cutoff) - 1
    return rows[index][1] if index >= 0 else None


def configs() -> list[Config]:
    return [
        Config(family, lookback, gap, stop, rr, hold, cards, schedule)
        for family in ("carry", "carry_with_momentum", "carry_on_pullback")
        for lookback in (20, 60)
        for gap in (0.0, 1.0)
        for stop in (1.5, 2.5)
        for rr in (1.0, 1.5)
        for hold in (20, 60)
        for cards in (1, 3)
        for schedule in ("weekly", "monthly")
    ]


def carry_ranks(
    data: dict[str, swing.Series], rates: dict[str, list[tuple[date, float]]],
    day: date, config: Config, excluded_currencies: set[str] | None = None,
) -> list[tuple[float, str, str, int]]:
    excluded_currencies = excluded_currencies or set()
    current_rates = {currency: known_rate(rows, day) for currency, rows in rates.items()}
    price_rows = swing.ranks(data, day, config)
    price_direction = {symbol: direction for _, symbol, direction, _ in price_rows}
    indexes = {symbol: index for _, symbol, _, index in price_rows}
    output = []
    for symbol, index in indexes.items():
        base, quote = symbol[:3], symbol[3:]
        if base in excluded_currencies or quote in excluded_currencies:
            continue
        base_rate, quote_rate = current_rates.get(base), current_rates.get(quote)
        if base_rate is None or quote_rate is None:
            continue
        gap = base_rate - quote_rate
        if abs(gap) < config.min_rate_gap:
            continue
        direction = "BUY" if gap > 0 else "SELL"
        if config.family == "carry_with_momentum" and price_direction.get(symbol) != direction:
            continue
        if config.family == "carry_on_pullback" and price_direction.get(symbol) == direction:
            continue
        output.append((abs(gap), symbol, direction, index))
    return sorted(output, key=lambda row: (-row[0], row[1]))


def simulate(
    data: dict[str, swing.Series], rates: dict[str, list[tuple[date, float]]],
    config: Config, allowed: set[date], cost_scale: float = 1.0,
    excluded_currencies: set[str] | None = None,
) -> list[dict[str, Any]]:
    output = []
    active: dict[str, datetime] = {}
    for day in swing.signal_dates(data, allowed, config.schedule):
        now = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        active = {symbol: until for symbol, until in active.items() if until > now}
        slots = min(config.cards, max(0, 3 - len(active)))
        if slots == 0:
            continue
        used = {currency for symbol in active for currency in (symbol[:3], symbol[3:])}
        placed = 0
        for strength, symbol, direction, index in carry_ranks(data, rates, day, config, excluded_currencies):
            if placed >= slots:
                break
            currencies = {symbol[:3], symbol[3:]}
            if symbol in active or currencies & used:
                continue
            trade = swing.evaluate(symbol, data[symbol], index, direction, strength, config, cost_scale)
            if not trade:
                continue
            output.append(trade)
            active[symbol] = datetime.fromisoformat(trade["exit_at"])
            used.update(currencies)
            placed += 1
    return output


def score(full: dict[str, Any], first: dict[str, Any], second: dict[str, Any]) -> float:
    if full["trades"] < 50:
        return -1000 + full["trades"]
    return min(first["avg_r"], second["avg_r"]) * 5 + full["avg_r"] * 3 - full["max_drawdown_r"] * 0.02


def bootstrap_mean(rows: list[dict[str, Any]], iterations: int = 10000) -> list[float] | None:
    values = [float(row["net_r"]) for row in rows]
    if len(values) < 2:
        return None
    rng = random.Random(20260909)
    samples = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(iterations))
    return [round(samples[int(iterations * 0.025)], 4), round(samples[int(iterations * 0.975)], 4)]


def render(payload: dict[str, Any]) -> str:
    meta, champion = payload["metadata"], payload["champion"]
    lines = [
        "# FX carry walk-forward", "",
        f"- Prices: Yahoo daily midpoint proxy, {meta['start']} through {meta['end']}, {len(meta['symbols'])} pairs.",
        "- Rates: OECD immediate/interbank monthly series distributed by FRED, delayed 45 days at every decision.",
        f"- Train through {meta['train_end']}; untouched validation from {meta['validation_start']}.",
        f"- Tested {meta['configurations']} carry, carry+momentum and carry-on-pullback variants.", "",
        f"Selected on training: `{champion['config']}`", "",
        f"- Train: {champion['train']['trades']} trades, {champion['train']['total_r']:.2f}R, avg {champion['train']['avg_r']:.3f}R, PF {champion['train']['profit_factor']:.2f}.",
        f"- Validation: {champion['validation']['trades']} trades, {champion['validation']['total_r']:.2f}R, avg {champion['validation']['avg_r']:.3f}R, PF {champion['validation']['profit_factor']:.2f}, max DD {champion['validation']['max_drawdown_r']:.2f}R.",
        f"- Double-cost validation: {champion['double_cost']['total_r']:.2f}R.",
        f"- Bootstrap 95% interval for mean validation R: {champion['bootstrap_mean_ci95']}.",
        f"- Gate: **{payload['production_gate']['status']}** — {payload['production_gate']['reason']}", "",
        "| Family | Training-selected config | Train R/PF | Validation R/PF |",
        "|---|---|---:|---:|",
    ]
    for row in payload["best_by_family"]:
        lines.append(f"| {row['family']} | `{row['config']}` | {row['train']['total_r']:.2f} / {row['train']['profit_factor']:.2f} | {row['validation']['total_r']:.2f} / {row['validation']['profit_factor']:.2f} |")
    lines.extend([
        "", "| Frequency | Training-selected config | Validation trades | Validation R/PF |",
        "|---|---|---:|---:|",
        *[
            f"| {row['schedule']} | `{row['config']}` | {row['validation']['trades']} | {row['validation']['total_r']:.2f} / {row['validation']['profit_factor']:.2f} |"
            for row in payload["best_by_schedule"]
        ],
        "", "| Card cap | Training-selected config | Validation trades | Validation R/PF | Double-cost R |",
        "|---:|---|---:|---:|---:|",
        *[
            f"| {row['cards']} | `{row['config']}` | {row['validation']['trades']} | {row['validation']['total_r']:.2f} / {row['validation']['profit_factor']:.2f} | {row['double_cost']['total_r']:.2f} |"
            for row in payload["best_by_cards"]
        ],
        "", "## Robustness diagnostics", "",
        f"- Effective parameter neighbors positive in validation: {payload['robustness']['positive_neighbors']}/{payload['robustness']['neighbor_count']}; median neighbor R {payload['robustness']['median_neighbor_total_r']:.2f}.",
        f"- Leave-one-currency-out positive cases: {payload['robustness']['positive_leave_one_out']}/{len(payload['robustness']['leave_one_currency_out'])}.",
        f"- Same winning rule with a three-card cap: train {payload['robustness']['three_card_extension']['train']['total_r']:.2f}R/PF {payload['robustness']['three_card_extension']['train']['profit_factor']:.2f}; validation {payload['robustness']['three_card_extension']['validation']['total_r']:.2f}R/PF {payload['robustness']['three_card_extension']['validation']['profit_factor']:.2f}, max DD {payload['robustness']['three_card_extension']['validation']['max_drawdown_r']:.2f}R over {payload['robustness']['three_card_extension']['validation']['trades']} fills.",
        "- Calendar-year totals: " + ", ".join(f"{row['year']}={row['total_r']:.2f}R" for row in payload['robustness']['yearly']) + ".", "",
        "", "Swap/carry cash income is intentionally not added because FBS CFD swap schedules differ from interbank rates. This tests whether the macro ranking improves entry direction itself. No production setting changed.", "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--price-cache", type=Path, default=Path("research/.cache/forex-daily"))
    parser.add_argument("--rate-cache", type=Path, default=Path("research/.cache/fred-rates"))
    parser.add_argument("--output-dir", type=Path, default=Path("research/results/forex-carry"))
    args = parser.parse_args()

    price_data = {}
    for symbol in swing.SYMBOLS:
        bars = swing.fetch(symbol, args.price_cache)
        if len(bars) >= 1500:
            price_data[symbol] = swing.Series(bars)
    swing.DATE_INDEX.clear()
    swing.DATE_INDEX.update({symbol: {bar.timestamp.date(): index for index, bar in enumerate(series.bars)} for symbol, series in price_data.items()})
    swing.RANK_CACHE.clear()
    rates, rate_errors = {}, {}
    for currency, series_id in RATE_SERIES.items():
        try:
            rows = fetch_rate(series_id, args.rate_cache)
            if not rows:
                raise RuntimeError("empty series")
            rates[currency] = rows
        except Exception as exc:  # pragma: no cover
            rate_errors[currency] = str(exc)
        time.sleep(0.15)
    if len(price_data) < 10 or len(rates) < 7:
        raise SystemExit(f"Insufficient price/rate data: {rate_errors}")

    dates = sorted({bar.timestamp.date() for series in price_data.values() for bar in series.bars if bar.timestamp.weekday() < 5})
    split = int(len(dates) * 0.70)
    train_dates, validation_dates = dates[:split], dates[split:]
    midpoint = len(train_dates) // 2
    first_dates, second_dates = set(train_dates[:midpoint]), set(train_dates[midpoint:])
    evaluated = []
    for config in configs():
        rows = simulate(price_data, rates, config, set(train_dates))
        full = swing.metrics(rows, len(train_dates))
        first = swing.metrics([row for row in rows if datetime.fromisoformat(row["signal_at"]).date() in first_dates], len(first_dates))
        second = swing.metrics([row for row in rows if datetime.fromisoformat(row["signal_at"]).date() in second_dates], len(second_dates))
        evaluated.append({"config": config, "train": full, "fold_a": first, "fold_b": second, "score": score(full, first, second)})
    evaluated.sort(key=lambda row: (row["score"], row["train"]["total_r"]), reverse=True)

    best_by_family = []
    for family in ("carry", "carry_with_momentum", "carry_on_pullback"):
        row = next(item for item in evaluated if item["config"].family == family)
        val_rows = simulate(price_data, rates, row["config"], set(validation_dates))
        best_by_family.append({"family": family, "config": row["config"].key, "train": row["train"], "validation": swing.metrics(val_rows, len(validation_dates))})
    best_by_schedule = []
    for schedule in ("weekly", "monthly"):
        row = next(item for item in evaluated if item["config"].schedule == schedule)
        val_rows = simulate(price_data, rates, row["config"], set(validation_dates))
        best_by_schedule.append({"schedule": schedule, "config": row["config"].key, "train": row["train"], "validation": swing.metrics(val_rows, len(validation_dates))})
    best_by_cards = []
    for cards in (1, 3):
        row = next(item for item in evaluated if item["config"].cards == cards)
        val_rows = simulate(price_data, rates, row["config"], set(validation_dates))
        stress_rows = simulate(price_data, rates, row["config"], set(validation_dates), 2.0)
        best_by_cards.append({
            "cards": cards, "config": row["config"].key, "train": row["train"],
            "validation": swing.metrics(val_rows, len(validation_dates)),
            "double_cost": swing.metrics(stress_rows, len(validation_dates)),
        })
    winner = evaluated[0]
    validation_rows = simulate(price_data, rates, winner["config"], set(validation_dates))
    validation = swing.metrics(validation_rows, len(validation_dates))
    double_cost = swing.metrics(simulate(price_data, rates, winner["config"], set(validation_dates), 2.0), len(validation_dates))
    neighbor_rows = []
    for item in evaluated:
        candidate = item["config"]
        if (
            candidate.family == winner["config"].family
            and candidate.min_rate_gap == winner["config"].min_rate_gap
            and candidate.cards == winner["config"].cards
            and candidate.schedule == winner["config"].schedule
        ):
            candidate_rows = simulate(price_data, rates, candidate, set(validation_dates))
            neighbor_rows.append({"config": candidate.key, "validation": swing.metrics(candidate_rows, len(validation_dates))})
    neighbor_totals = [row["validation"]["total_r"] for row in neighbor_rows]
    leave_one_out = []
    for currency in sorted(rates):
        rows = simulate(price_data, rates, winner["config"], set(validation_dates), excluded_currencies={currency})
        leave_one_out.append({"currency": currency, "validation": swing.metrics(rows, len(validation_dates))})
    full_rows = simulate(price_data, rates, winner["config"], set(dates))
    three_card_config = Config(**{**asdict(winner["config"]), "cards": 3})
    three_card_train = simulate(price_data, rates, three_card_config, set(train_dates))
    three_card_rows = simulate(price_data, rates, three_card_config, set(validation_dates))
    three_card_stress = simulate(price_data, rates, three_card_config, set(validation_dates), 2.0)
    yearly = []
    for year in sorted({datetime.fromisoformat(row["signal_at"]).year for row in full_rows}):
        rows = [row for row in full_rows if datetime.fromisoformat(row["signal_at"]).year == year]
        yearly.append({"year": year, **swing.metrics(rows, max(1, sum(day.year == year for day in dates)))})
    robustness = {
        "neighbor_count": len(neighbor_rows),
        "positive_neighbors": sum(row["validation"]["total_r"] > 0 for row in neighbor_rows),
        "median_neighbor_total_r": round(statistics.median(neighbor_totals), 4),
        "neighbors": neighbor_rows,
        "positive_leave_one_out": sum(row["validation"]["total_r"] > 0 for row in leave_one_out),
        "leave_one_currency_out": leave_one_out,
        "three_card_extension": {
            "config": three_card_config.key,
            "train": swing.metrics(three_card_train, len(train_dates)),
            "validation": swing.metrics(three_card_rows, len(validation_dates)),
            "double_cost": swing.metrics(three_card_stress, len(validation_dates)),
        },
        "yearly": yearly,
    }
    conditions = {
        "at_least_30_validation_trades": validation["trades"] >= 30,
        "avg_r_at_least_0_08": validation["avg_r"] >= 0.08,
        "profit_factor_at_least_1_20": validation["profit_factor"] >= 1.20,
        "max_drawdown_below_12r": validation["max_drawdown_r"] < 12,
        "positive_at_double_cost": double_cost["total_r"] > 0,
    }
    passed = all(conditions.values())
    failed = [key for key, okay in conditions.items() if not okay]
    payload = {
        "metadata": {"generated_at": datetime.now(timezone.utc).isoformat(), "start": dates[0].isoformat(), "end": dates[-1].isoformat(), "train_end": train_dates[-1].isoformat(), "validation_start": validation_dates[0].isoformat(), "symbols": sorted(price_data), "rate_series": RATE_SERIES, "rate_errors": rate_errors, "configurations": len(evaluated)},
        "champion": {"config": winner["config"].key, "parameters": asdict(winner["config"]), "train": winner["train"], "fold_a": winner["fold_a"], "fold_b": winner["fold_b"], "validation": validation, "double_cost": double_cost, "bootstrap_mean_ci95": bootstrap_mean(validation_rows), "validation_rows": validation_rows},
        "best_by_family": best_by_family, "best_by_schedule": best_by_schedule,
        "best_by_cards": best_by_cards,
        "robustness": robustness,
        "production_gate": {"status": "PASS — candidate for independent demo forward test" if passed else "FAIL — do not deploy", "conditions": conditions, "reason": "All conditions passed." if passed else "Failed: " + ", ".join(failed)},
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "report.md").write_text(render(payload))
    print(json.dumps({"report": str(args.output_dir / "report.md"), "rates": sorted(rates), "rate_errors": rate_errors, "configurations": len(evaluated), "champion": winner["config"].key, "train": winner["train"], "validation": validation, "double_cost": double_cost, "gate": payload["production_gate"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
