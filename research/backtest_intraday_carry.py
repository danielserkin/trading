#!/usr/bin/env python3
"""Intraday FX entries conditioned on lagged macro carry direction."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import backtest_currency_strength as hourly
from backtest_fx_carry import RATE_SERIES, fetch_rate, known_rate


@dataclass(frozen=True)
class Config:
    family: str
    lookback_hours: int
    min_rate_gap: float
    stop_atr: float
    rr: float
    horizon_hours: int
    cards: int
    signal_hour: int
    disjoint_currencies: bool = True

    @property
    def min_strength(self) -> float:
        return 0.0

    @property
    def key(self) -> str:
        return (
            f"{self.family}|lb={self.lookback_hours}h|carrygap={self.min_rate_gap:g}|stop={self.stop_atr:g}atr|"
            f"rr={self.rr:g}|hold={self.horizon_hours}h|cards={self.cards}|utc={self.signal_hour}|disjoint"
        )


def configs() -> list[Config]:
    return [
        Config(family, lookback, gap, stop, rr, horizon, cards, hour)
        for family in ("carry", "carry_with_momentum", "carry_on_pullback")
        for lookback in (24, 72, 120)
        for gap in (0.5, 1.0)
        for stop in (1.2, 1.8)
        for rr in (1.0, 1.5)
        for horizon in (12, 24, 48)
        for cards in (1, 3)
        for hour in (7, 12)
    ]


def carry_ranks(
    data: dict[str, hourly.Series], rates: dict[str, list[tuple[date, float]]],
    signal_at: datetime, config: Config,
) -> list[tuple[float, str, str, int]]:
    price_rows = hourly.ranked_pairs(data, signal_at, config)
    price_direction = {symbol: direction for _, symbol, direction, _ in price_rows}
    indexes = {symbol: index for _, symbol, _, index in price_rows}
    current_rates = {currency: known_rate(rows, signal_at.date()) for currency, rows in rates.items()}
    output = []
    for symbol, index in indexes.items():
        base, quote = symbol[:3], symbol[3:]
        base_rate, quote_rate = current_rates.get(base), current_rates.get(quote)
        if base_rate is None or quote_rate is None:
            continue
        rate_gap = base_rate - quote_rate
        if abs(rate_gap) < config.min_rate_gap:
            continue
        direction = "BUY" if rate_gap > 0 else "SELL"
        if config.family == "carry_with_momentum" and price_direction.get(symbol) != direction:
            continue
        if config.family == "carry_on_pullback" and price_direction.get(symbol) == direction:
            continue
        output.append((abs(rate_gap), symbol, direction, index))
    return sorted(output, key=lambda row: (-row[0], row[1]))


def simulate(
    data: dict[str, hourly.Series], rates: dict[str, list[tuple[date, float]]],
    config: Config, allowed_dates: set[date], cost_scale: float = 1.0,
) -> list[dict[str, Any]]:
    output = []
    active_until: dict[str, datetime] = {}
    for signal_at in hourly.decision_times(data, config.signal_hour, allowed_dates):
        active_until = {symbol: until for symbol, until in active_until.items() if until > signal_at}
        slots = min(config.cards, max(0, 3 - len(active_until)))
        if slots == 0:
            continue
        used = {currency for symbol in active_until for currency in (symbol[:3], symbol[3:])}
        placed = 0
        for strength, symbol, direction, index in carry_ranks(data, rates, signal_at, config):
            if placed >= slots:
                break
            currencies = {symbol[:3], symbol[3:]}
            if symbol in active_until or currencies & used:
                continue
            trade = hourly.evaluate(symbol, data[symbol], index, direction, strength, config)
            if not trade:
                continue
            if cost_scale != 1.0:
                trade["net_r"] = round(float(trade["gross_r"]) - cost_scale * float(trade["cost_r"]), 5)
            output.append(trade)
            active_until[symbol] = datetime.fromisoformat(trade["exit_at"])
            used.update(currencies)
            placed += 1
    return output


def selection_score(full: dict[str, Any], first: dict[str, Any], second: dict[str, Any]) -> float:
    if full["trades"] < 100:
        return -1000 + full["trades"]
    return min(first["avg_r"], second["avg_r"]) * 5 + full["avg_r"] * 3 + full["coverage_percent"] / 100 - full["max_drawdown_r"] * 0.02


def render(payload: dict[str, Any]) -> str:
    meta, champion = payload["metadata"], payload["champion"]
    lines = [
        "# Intraday carry-conditioned walk-forward", "",
        f"- Hourly Yahoo prices from {meta['start']} through {meta['end']}; lagged OECD/FRED rates for eight currencies.",
        f"- Train through {meta['train_end']}; untouched validation from {meta['validation_start']}.",
        f"- Tested {meta['configurations']} carry-only, carry+momentum and carry-on-pullback combinations with 1/3 card caps.", "",
        f"Selected on training: `{champion['config']}`", "",
        f"- Train: {champion['train']['trades']} trades, {champion['train']['total_r']:.2f}R, avg {champion['train']['avg_r']:.3f}R, PF {champion['train']['profit_factor']:.2f}, coverage {champion['train']['coverage_percent']:.1f}%.",
        f"- Validation: {champion['validation']['trades']} trades, {champion['validation']['total_r']:.2f}R, avg {champion['validation']['avg_r']:.3f}R, PF {champion['validation']['profit_factor']:.2f}, DD {champion['validation']['max_drawdown_r']:.2f}R, coverage {champion['validation']['coverage_percent']:.1f}%.",
        f"- Double-cost validation: {champion['double_cost']['total_r']:.2f}R.",
        f"- Gate: **{payload['production_gate']['status']}** — {payload['production_gate']['reason']}", "",
        "| Card cap | Training-selected config | Validation trades | Validation R/PF/DD |",
        "|---:|---|---:|---:|",
    ]
    for row in payload["best_by_cards"]:
        metric = row["validation"]
        lines.append(f"| {row['cards']} | `{row['config']}` | {metric['trades']} | {metric['total_r']:.2f} / {metric['profit_factor']:.2f} / {metric['max_drawdown_r']:.2f} |")
    lines.extend(["", "The test does not add theoretical carry income; it asks whether the rate differential improves intraday direction and TP attainment. No production setting changed.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--price-cache", type=Path, default=Path("research/.cache/forex-hourly"))
    parser.add_argument("--rate-cache", type=Path, default=Path("research/.cache/fred-rates"))
    parser.add_argument("--output-dir", type=Path, default=Path("research/results/forex-intraday-carry"))
    args = parser.parse_args()

    data = {}
    for symbol in hourly.SYMBOLS:
        bars = hourly.fetch(symbol, args.price_cache)
        if len(bars) >= 4000:
            data[symbol] = hourly.Series(bars)
    rates = {currency: fetch_rate(series_id, args.rate_cache) for currency, series_id in RATE_SERIES.items()}
    dates = sorted({bar.timestamp.date() for series in data.values() for bar in series.bars if bar.timestamp.weekday() < 5})
    split = int(len(dates) * 0.70)
    train_dates, validation_dates = dates[:split], dates[split:]
    midpoint = len(train_dates) // 2
    first_dates, second_dates = set(train_dates[:midpoint]), set(train_dates[midpoint:])
    hourly.DECISION_CACHE.clear()
    hourly.RANK_CACHE.clear()
    evaluated = []
    for config in configs():
        rows = simulate(data, rates, config, set(train_dates))
        full = hourly.metrics(rows, len(train_dates))
        first = hourly.metrics([row for row in rows if datetime.fromisoformat(row["signal_at"]).date() in first_dates], len(first_dates))
        second = hourly.metrics([row for row in rows if datetime.fromisoformat(row["signal_at"]).date() in second_dates], len(second_dates))
        evaluated.append({"config": config, "train": full, "fold_a": first, "fold_b": second, "score": selection_score(full, first, second)})
    evaluated.sort(key=lambda row: (row["score"], row["train"]["total_r"]), reverse=True)
    winner = evaluated[0]
    validation_rows = simulate(data, rates, winner["config"], set(validation_dates))
    validation = hourly.metrics(validation_rows, len(validation_dates))
    double_cost = hourly.metrics(simulate(data, rates, winner["config"], set(validation_dates), 2.0), len(validation_dates))
    best_by_cards = []
    for cards in (1, 3):
        row = next(item for item in evaluated if item["config"].cards == cards)
        rows = simulate(data, rates, row["config"], set(validation_dates))
        best_by_cards.append({"cards": cards, "config": row["config"].key, "train": row["train"], "validation": hourly.metrics(rows, len(validation_dates))})
    conditions = {
        "at_least_50_validation_trades": validation["trades"] >= 50,
        "coverage_at_least_60pct": validation["coverage_percent"] >= 60,
        "avg_r_at_least_0_08": validation["avg_r"] >= 0.08,
        "profit_factor_at_least_1_20": validation["profit_factor"] >= 1.20,
        "max_drawdown_below_12r": validation["max_drawdown_r"] < 12,
        "positive_at_double_cost": double_cost["total_r"] > 0,
    }
    passed = all(conditions.values())
    failed = [key for key, okay in conditions.items() if not okay]
    payload = {
        "metadata": {"generated_at": datetime.now(timezone.utc).isoformat(), "start": dates[0].isoformat(), "end": dates[-1].isoformat(), "train_end": train_dates[-1].isoformat(), "validation_start": validation_dates[0].isoformat(), "symbols": sorted(data), "configurations": len(evaluated)},
        "champion": {"config": winner["config"].key, "parameters": asdict(winner["config"]), "train": winner["train"], "fold_a": winner["fold_a"], "fold_b": winner["fold_b"], "validation": validation, "double_cost": double_cost, "validation_rows": validation_rows},
        "best_by_cards": best_by_cards,
        "production_gate": {"status": "PASS — candidate for independent demo forward test" if passed else "FAIL — do not deploy", "conditions": conditions, "reason": "All conditions passed." if passed else "Failed: " + ", ".join(failed)},
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "report.md").write_text(render(payload))
    print(json.dumps({"report": str(args.output_dir / "report.md"), "configurations": len(evaluated), "champion": winner["config"].key, "train": winner["train"], "validation": validation, "double_cost": double_cost, "best_by_cards": best_by_cards, "gate": payload["production_gate"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
