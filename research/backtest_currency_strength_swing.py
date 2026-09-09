#!/usr/bin/env python3
"""Long-horizon cross-sectional FX momentum/reversal walk-forward."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from backtest_currency_strength import Bar, Series, max_drawdown, pip_size, spread_pips


YAHOO_URL = "https://query2.finance.yahoo.com/v8/finance/chart"
SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURJPY", "GBPJPY", "EURGBP", "AUDJPY", "EURAUD", "GBPAUD", "GBPCAD", "GBPCHF",
]


@dataclass(frozen=True)
class Config:
    family: str
    lookback_days: int
    min_strength: float
    stop_atr: float
    rr: float
    hold_bars: int
    cards: int
    schedule: str

    @property
    def key(self) -> str:
        return (
            f"{self.family}|lb={self.lookback_days}d|min={self.min_strength:g}|stop={self.stop_atr:g}atr|"
            f"rr={self.rr:g}|hold={self.hold_bars}d|cards={self.cards}|{self.schedule}"
        )


def fetch(symbol: str, cache_dir: Path) -> list[Bar]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{symbol}-10y-1d.json"
    if path.exists():
        payload = json.loads(path.read_text())
    else:
        ticker = urllib.parse.quote(f"{symbol}=X", safe="")
        query = urllib.parse.urlencode({"range": "10y", "interval": "1d", "includePrePost": "false"})
        request = urllib.request.Request(
            f"{YAHOO_URL}/{ticker}?{query}",
            headers={"User-Agent": "Mozilla/5.0 currency-strength-swing-research/1.0"},
        )
        error: Exception | None = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                path.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
                break
            except Exception as exc:  # pragma: no cover
                error = exc
                time.sleep(2 * (attempt + 1))
        else:
            raise RuntimeError(str(error))
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(str(chart["error"]))
    result = (chart.get("result") or [None])[0]
    if not result:
        raise RuntimeError("empty result")
    stamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    bars = []
    for index, stamp in enumerate(stamps):
        values = [quote.get(name, [None] * len(stamps))[index] for name in ("open", "high", "low", "close")]
        if any(value is None for value in values):
            continue
        bars.append(Bar(datetime.fromtimestamp(int(stamp), tz=timezone.utc), *[float(value) for value in values]))
    return sorted(bars, key=lambda bar: bar.timestamp)


def configs() -> list[Config]:
    return [
        Config(family, lookback, threshold, stop, rr, hold, cards, schedule)
        for family in ("momentum", "reversal")
        for lookback in (20, 60, 120, 240)
        for threshold in (0.0, 1.0)
        for stop in (1.5, 2.5)
        for rr in (1.0, 1.5)
        for hold in (20, 60)
        for cards in (1, 3)
        for schedule in ("daily", "weekly", "monthly")
    ]


def signal_dates(data: dict[str, Series], allowed: set[date], schedule: str) -> list[date]:
    dates = sorted({bar.timestamp.date() for series in data.values() for bar in series.bars if bar.timestamp.date() in allowed})
    if schedule == "daily":
        return dates
    if schedule == "weekly":
        return [day for day in dates if day.weekday() == 0]
    months = {}
    for day in dates:
        months.setdefault((day.year, day.month), day)
    return list(months.values())


RANK_CACHE: dict[tuple[int, str], list[tuple[float, str, str, int]]] = {}
DATE_INDEX: dict[str, dict[date, int]] = {}


def ranks(data: dict[str, Series], day: date, config: Config) -> list[tuple[float, str, str, int]]:
    cache_key = (config.lookback_days, day.isoformat())
    if cache_key not in RANK_CACHE:
        currency_moves: dict[str, list[float]] = defaultdict(list)
        pair_indexes = {}
        for symbol, series in data.items():
            index = DATE_INDEX[symbol].get(day)
            if index is None:
                continue
            if index < config.lookback_days or index + 1 >= len(series.bars):
                continue
            atr = series.atr(index, 14)
            if not math.isfinite(atr) or atr <= 0:
                continue
            move = (series.bars[index].close - series.bars[index - config.lookback_days].close) / atr
            base, quote = symbol[:3], symbol[3:]
            currency_moves[base].append(move)
            currency_moves[quote].append(-move)
            pair_indexes[symbol] = index
        currency_score = {key: statistics.fmean(values) for key, values in currency_moves.items() if len(values) >= 2}
        raw = []
        for symbol, index in pair_indexes.items():
            base, quote = symbol[:3], symbol[3:]
            if base not in currency_score or quote not in currency_score:
                continue
            strength = currency_score[base] - currency_score[quote]
            raw.append((abs(strength), symbol, "BUY" if strength > 0 else "SELL", index))
        RANK_CACHE[cache_key] = sorted(raw, key=lambda row: (-row[0], row[1]))
    output = []
    for strength, symbol, direction, index in RANK_CACHE[cache_key]:
        if strength < config.min_strength:
            continue
        if config.family == "reversal":
            direction = "SELL" if direction == "BUY" else "BUY"
        output.append((strength, symbol, direction, index))
    return output


def evaluate(symbol: str, series: Series, index: int, direction: str, strength: float, config: Config, cost_scale: float) -> dict[str, Any] | None:
    if index + 1 >= len(series.bars):
        return None
    risk = series.atr(index, 14) * config.stop_atr
    if not math.isfinite(risk) or risk <= 0:
        return None
    entry_bar = series.bars[index + 1]
    entry = entry_bar.open
    stop = entry - risk if direction == "BUY" else entry + risk
    target = entry + config.rr * risk if direction == "BUY" else entry - config.rr * risk
    last = entry_bar
    result, gross = "time_exit", None
    for bar in series.bars[index + 1:index + 2 + config.hold_bars]:
        last = bar
        hit_stop = bar.low <= stop if direction == "BUY" else bar.high >= stop
        hit_target = bar.high >= target if direction == "BUY" else bar.low <= target
        if hit_stop:
            result, gross = "stop", -1.0
            break
        if hit_target:
            result, gross = "target", config.rr
            break
    if gross is None:
        gross = ((last.close - entry) if direction == "BUY" else (entry - last.close)) / risk
        gross = max(-1.0, min(config.rr, gross))
    cost_r = (spread_pips(symbol) + 0.2) * pip_size(symbol) * cost_scale / risk
    return {
        "symbol": symbol, "direction": direction, "signal_at": series.bars[index].timestamp.isoformat(),
        "entry_at": entry_bar.timestamp.isoformat(), "exit_at": last.timestamp.isoformat(),
        "strength": round(strength, 5), "result": result, "gross_r": round(gross, 5),
        "cost_r": round(cost_r, 5), "net_r": round(gross - cost_r, 5), "config": config.key,
    }


def simulate(data: dict[str, Series], config: Config, allowed: set[date], cost_scale: float = 1.0) -> list[dict[str, Any]]:
    output = []
    active: dict[str, datetime] = {}
    for day in signal_dates(data, allowed, config.schedule):
        now = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        active = {symbol: until for symbol, until in active.items() if until > now}
        slots = max(0, 3 - len(active))
        if slots == 0:
            continue
        used_currencies = {currency for symbol in active for currency in (symbol[:3], symbol[3:])}
        placed = 0
        for strength, symbol, direction, index in ranks(data, day, config):
            if placed >= min(config.cards, slots):
                break
            if symbol in active:
                continue
            currencies = {symbol[:3], symbol[3:]}
            if currencies & used_currencies:
                continue
            trade = evaluate(symbol, data[symbol], index, direction, strength, config, cost_scale)
            if not trade:
                continue
            output.append(trade)
            active[symbol] = datetime.fromisoformat(trade["exit_at"])
            used_currencies.update(currencies)
            placed += 1
    return output


def metrics(rows: list[dict[str, Any]], days: int) -> dict[str, Any]:
    values = [float(row["net_r"]) for row in rows]
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value <= 0)
    covered = {row["signal_at"][:10] for row in rows}
    return {
        "trades": len(rows), "wins": sum(value > 0 for value in values),
        "win_rate": round(100 * sum(value > 0 for value in values) / len(values), 2) if values else 0.0,
        "total_r": round(sum(values), 4), "avg_r": round(statistics.fmean(values), 4) if values else 0.0,
        "profit_factor": round(gains / losses, 3) if losses else (999.0 if gains else 0.0),
        "max_drawdown_r": round(max_drawdown(values), 4), "days_with_signal": len(covered),
        "coverage_percent": round(100 * len(covered) / days, 2) if days else 0.0,
        "targets": sum(row["result"] == "target" for row in rows),
        "stops": sum(row["result"] == "stop" for row in rows),
        "time_exits": sum(row["result"] == "time_exit" for row in rows),
    }


def selection_score(full: dict[str, Any], first: dict[str, Any], second: dict[str, Any]) -> float:
    if full["trades"] < 50:
        return -1000 + full["trades"]
    return min(first["avg_r"], second["avg_r"]) * 5 + full["avg_r"] * 3 - full["max_drawdown_r"] * 0.02


def render(payload: dict[str, Any]) -> str:
    meta, champion = payload["metadata"], payload["champion"]
    return "\n".join([
        "# Swing currency-strength walk-forward", "",
        f"- Data: Yahoo daily midpoint proxy, {meta['start']} through {meta['end']}, {len(meta['symbols'])} pairs.",
        f"- Train through {meta['train_end']}; untouched validation from {meta['validation_start']}.",
        f"- Tested {meta['configurations']} predeclared momentum/reversal variants at daily, weekly and monthly frequency.", "",
        f"Selected on training: `{champion['config']}`", "",
        f"- Train: {champion['train']['trades']} trades, {champion['train']['total_r']:.2f}R, avg {champion['train']['avg_r']:.3f}R, PF {champion['train']['profit_factor']:.2f}.",
        f"- Validation: {champion['validation']['trades']} trades, {champion['validation']['total_r']:.2f}R, avg {champion['validation']['avg_r']:.3f}R, PF {champion['validation']['profit_factor']:.2f}, max DD {champion['validation']['max_drawdown_r']:.2f}R.",
        f"- Double-cost validation: {champion['double_cost']['total_r']:.2f}R.",
        f"- Gate: **{payload['production_gate']['status']}** — {payload['production_gate']['reason']}", "",
        "## Best training choice by frequency", "",
        "| Frequency | Configuration | Train R/PF | Validation R/PF | Validation fills |",
        "|---|---|---:|---:|---:|",
        *[
            f"| {row['schedule']} | `{row['config']}` | {row['train']['total_r']:.2f} / {row['train']['profit_factor']:.2f} | "
            f"{row['validation']['total_r']:.2f} / {row['validation']['profit_factor']:.2f} | {row['validation']['trades']} |"
            for row in payload["best_by_schedule"]
        ], "",
        "This long-horizon test is closer to published currency-momentum portfolio horizons, but still uses spot proxies and explicit retail-style TP/SL exits. No production setting changed.", "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=Path("research/.cache/forex-daily"))
    parser.add_argument("--output-dir", type=Path, default=Path("research/results/forex-currency-strength-swing"))
    args = parser.parse_args()
    raw, errors = {}, {}
    for symbol in SYMBOLS:
        try:
            bars = fetch(symbol, args.cache_dir)
            if len(bars) < 1500:
                raise RuntimeError(f"only {len(bars)} bars")
            raw[symbol] = bars
        except Exception as exc:  # pragma: no cover
            errors[symbol] = str(exc)
        time.sleep(0.15)
    if len(raw) < 10:
        raise SystemExit(f"Insufficient data: {errors}")
    data = {symbol: Series(bars) for symbol, bars in raw.items()}
    DATE_INDEX.update({
        symbol: {bar.timestamp.date(): index for index, bar in enumerate(series.bars)}
        for symbol, series in data.items()
    })
    dates = sorted({bar.timestamp.date() for series in data.values() for bar in series.bars if bar.timestamp.weekday() < 5})
    split = int(len(dates) * 0.70)
    train_dates, validation_dates = dates[:split], dates[split:]
    midpoint = len(train_dates) // 2
    first_dates, second_dates = set(train_dates[:midpoint]), set(train_dates[midpoint:])
    evaluated = []
    for config in configs():
        rows = simulate(data, config, set(train_dates))
        full = metrics(rows, len(train_dates))
        first = metrics([row for row in rows if datetime.fromisoformat(row["signal_at"]).date() in first_dates], len(first_dates))
        second = metrics([row for row in rows if datetime.fromisoformat(row["signal_at"]).date() in second_dates], len(second_dates))
        evaluated.append({"config": config, "train": full, "fold_a": first, "fold_b": second, "score": selection_score(full, first, second)})
    evaluated.sort(key=lambda row: (row["score"], row["train"]["total_r"]), reverse=True)
    top = []
    for rank, row in enumerate(evaluated[:5], 1):
        validation_rows = simulate(data, row["config"], set(validation_dates))
        top.append({"rank": rank, "config": row["config"].key, "train": row["train"], "fold_a": row["fold_a"], "fold_b": row["fold_b"], "validation": metrics(validation_rows, len(validation_dates)), "rows": validation_rows})
    best_by_schedule = []
    for schedule in ("daily", "weekly", "monthly"):
        row = next(item for item in evaluated if item["config"].schedule == schedule)
        validation_rows = simulate(data, row["config"], set(validation_dates))
        best_by_schedule.append({
            "schedule": schedule, "config": row["config"].key,
            "train": row["train"], "fold_a": row["fold_a"], "fold_b": row["fold_b"],
            "validation": metrics(validation_rows, len(validation_dates)),
        })
    winner = evaluated[0]
    validation = top[0]["validation"]
    double_cost = metrics(simulate(data, winner["config"], set(validation_dates), 2.0), len(validation_dates))
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
        "metadata": {"generated_at": datetime.now(timezone.utc).isoformat(), "start": dates[0].isoformat(), "end": dates[-1].isoformat(), "train_end": train_dates[-1].isoformat(), "validation_start": validation_dates[0].isoformat(), "symbols": sorted(data), "errors": errors, "configurations": len(evaluated)},
        "champion": {"config": winner["config"].key, "parameters": asdict(winner["config"]), "train": winner["train"], "fold_a": winner["fold_a"], "fold_b": winner["fold_b"], "validation": validation, "double_cost": double_cost, "validation_rows": top[0]["rows"]},
        "top_five": top, "best_by_schedule": best_by_schedule,
        "production_gate": {"status": "PASS — candidate for independent demo forward test" if passed else "FAIL — do not deploy", "conditions": conditions, "reason": "All conditions passed." if passed else "Failed: " + ", ".join(failed)},
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "report.md").write_text(render(payload))
    print(json.dumps({"report": str(args.output_dir / "report.md"), "symbols": len(data), "errors": errors, "configurations": len(evaluated), "champion": winner["config"].key, "train": winner["train"], "validation": validation, "double_cost": double_cost, "gate": payload["production_gate"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
