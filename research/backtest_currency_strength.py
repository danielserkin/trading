#!/usr/bin/env python3
"""Cross-sectional currency-strength walk-forward on hourly FX candles."""

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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


YAHOO_URL = "https://query2.finance.yahoo.com/v8/finance/chart"
SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURJPY", "GBPJPY", "EURGBP", "AUDJPY", "EURAUD", "GBPAUD", "GBPCAD", "GBPCHF",
]
DECISION_CACHE: dict[tuple[int, tuple[str, ...]], list[datetime]] = {}
RANK_CACHE: dict[tuple[int, str], list[tuple[float, str, str, int]]] = {}


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


class Series:
    def __init__(self, bars: list[Bar]) -> None:
        self.bars = bars
        self.index = {bar.timestamp: index for index, bar in enumerate(bars)}
        self.tr_prefix = [0.0]
        previous = bars[0].close
        for bar in bars:
            true_range = max(bar.high - bar.low, abs(bar.high - previous), abs(bar.low - previous))
            self.tr_prefix.append(self.tr_prefix[-1] + true_range)
            previous = bar.close

    def atr(self, index: int, length: int = 24) -> float:
        if index + 1 < length:
            return math.nan
        return (self.tr_prefix[index + 1] - self.tr_prefix[index + 1 - length]) / length


@dataclass(frozen=True)
class Config:
    family: str
    lookback_hours: int
    min_strength: float
    stop_atr: float
    rr: float
    horizon_hours: int
    cards: int
    signal_hour: int
    disjoint_currencies: bool

    @property
    def key(self) -> str:
        correlation = "disjoint" if self.disjoint_currencies else "shared_ok"
        return (
            f"{self.family}|lb={self.lookback_hours}h|min={self.min_strength:g}|stop={self.stop_atr:g}atr|"
            f"rr={self.rr:g}|hold={self.horizon_hours}h|cards={self.cards}|utc={self.signal_hour}|{correlation}"
        )


def fetch(symbol: str, cache_dir: Path) -> list[Bar]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{symbol}-2y-1h.json"
    if path.exists():
        payload = json.loads(path.read_text())
    else:
        ticker = urllib.parse.quote(f"{symbol}=X", safe="")
        query = urllib.parse.urlencode({"range": "2y", "interval": "1h", "includePrePost": "false"})
        request = urllib.request.Request(
            f"{YAHOO_URL}/{ticker}?{query}",
            headers={"User-Agent": "Mozilla/5.0 currency-strength-research/1.0"},
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
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    bars = []
    for index, stamp in enumerate(timestamps):
        values = [quote.get(name, [None] * len(timestamps))[index] for name in ("open", "high", "low", "close")]
        if any(value is None for value in values):
            continue
        bars.append(Bar(datetime.fromtimestamp(int(stamp), tz=timezone.utc), *[float(value) for value in values]))
    return sorted(bars, key=lambda bar: bar.timestamp)


def pip_size(symbol: str) -> float:
    return 0.01 if symbol.endswith("JPY") else 0.0001


def spread_pips(symbol: str) -> float:
    return 1.2 if symbol in {"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD"} else 1.8


def configurations() -> list[Config]:
    return [
        Config(family, lookback, threshold, stop, rr, horizon, cards, hour, disjoint)
        for family in ("momentum", "reversal")
        for lookback in (24, 72, 120)
        for threshold in (0.0, 0.5, 1.0)
        for stop in (1.2, 1.8)
        for rr in (1.0, 1.5, 2.0)
        for horizon in (24, 48)
        for cards in (1, 2, 3)
        for hour in (7, 12)
        for disjoint in (False, True)
    ]


def decision_times(data: dict[str, Series], hour: int, allowed: set[date]) -> list[datetime]:
    cache_key = (hour, tuple(sorted(day.isoformat() for day in allowed)))
    if cache_key in DECISION_CACHE:
        return DECISION_CACHE[cache_key]
    stamps = {
        bar.timestamp + timedelta(hours=1)
        for series in data.values() for bar in series.bars
        if (bar.timestamp + timedelta(hours=1)).hour == hour
        and (bar.timestamp + timedelta(hours=1)).date() in allowed
    }
    DECISION_CACHE[cache_key] = sorted(stamps)
    return DECISION_CACHE[cache_key]


def ranked_pairs(data: dict[str, Series], signal_at: datetime, config: Config) -> list[tuple[float, str, str, int]]:
    cache_key = (config.lookback_hours, signal_at.isoformat())
    if cache_key in RANK_CACHE:
        raw_ranked = RANK_CACHE[cache_key]
        output = []
        for strength, symbol, raw_direction, index in raw_ranked:
            if strength < config.min_strength:
                continue
            direction = raw_direction if config.family == "momentum" else ("SELL" if raw_direction == "BUY" else "BUY")
            output.append((strength, symbol, direction, index))
        return output
    bar_stamp = signal_at - timedelta(hours=1)
    currency_values: dict[str, list[float]] = defaultdict(list)
    indexes: dict[str, int] = {}
    for symbol, series in data.items():
        index = series.index.get(bar_stamp)
        if index is None or index < config.lookback_hours or index + 1 >= len(series.bars):
            continue
        atr = series.atr(index)
        if not math.isfinite(atr) or atr <= 0:
            continue
        move = (series.bars[index].close - series.bars[index - config.lookback_hours].close) / atr
        base, quote = symbol[:3], symbol[3:]
        currency_values[base].append(move)
        currency_values[quote].append(-move)
        indexes[symbol] = index
    currency_score = {
        currency: statistics.fmean(values) for currency, values in currency_values.items() if len(values) >= 2
    }
    raw_ranked = []
    for symbol, index in indexes.items():
        base, quote = symbol[:3], symbol[3:]
        if base not in currency_score or quote not in currency_score:
            continue
        strength = currency_score[base] - currency_score[quote]
        raw_direction = "BUY" if strength > 0 else "SELL"
        raw_ranked.append((abs(strength), symbol, raw_direction, index))
    RANK_CACHE[cache_key] = sorted(raw_ranked, key=lambda item: (-item[0], item[1]))
    return ranked_pairs(data, signal_at, config)


def evaluate(
    symbol: str, series: Series, index: int, direction: str, strength: float, config: Config,
) -> dict[str, Any] | None:
    if index + 1 >= len(series.bars):
        return None
    risk = series.atr(index) * config.stop_atr
    if not math.isfinite(risk) or risk <= 0:
        return None
    entry_bar = series.bars[index + 1]
    entry = entry_bar.open
    stop = entry - risk if direction == "BUY" else entry + risk
    target = entry + config.rr * risk if direction == "BUY" else entry - config.rr * risk
    deadline = entry_bar.timestamp + timedelta(hours=config.horizon_hours)
    result, last, gross_r = "time_exit", entry_bar, None
    for bar in series.bars[index + 1:]:
        if bar.timestamp > deadline:
            break
        last = bar
        hit_stop = bar.low <= stop if direction == "BUY" else bar.high >= stop
        hit_target = bar.high >= target if direction == "BUY" else bar.low <= target
        if hit_stop:
            result, gross_r = "stop", -1.0
            break
        if hit_target:
            result, gross_r = "target", config.rr
            break
    if gross_r is None:
        gross_r = ((last.close - entry) if direction == "BUY" else (entry - last.close)) / risk
        gross_r = max(-1.0, min(config.rr, gross_r))
    cost_r = (spread_pips(symbol) + 0.2) * pip_size(symbol) / risk
    return {
        "symbol": symbol, "direction": direction,
        "signal_at": (series.bars[index].timestamp + timedelta(hours=1)).isoformat(),
        "entry_at": entry_bar.timestamp.isoformat(), "exit_at": last.timestamp.isoformat(),
        "strength": round(strength, 5), "entry": entry, "stop": stop, "target": target,
        "result": result, "gross_r": round(gross_r, 5), "cost_r": round(cost_r, 5),
        "net_r": round(gross_r - cost_r, 5), "config": config.key,
    }


def simulate(data: dict[str, Series], config: Config, allowed_dates: set[date], cost_scale: float = 1.0) -> list[dict[str, Any]]:
    output = []
    active_until: dict[str, datetime] = {}
    for signal_at in decision_times(data, config.signal_hour, allowed_dates):
        used_currencies: set[str] = set()
        cards = 0
        for strength, symbol, direction, index in ranked_pairs(data, signal_at, config):
            if cards >= config.cards:
                break
            if active_until.get(symbol, signal_at) > signal_at:
                continue
            currencies = {symbol[:3], symbol[3:]}
            if config.disjoint_currencies and currencies & used_currencies:
                continue
            trade = evaluate(symbol, data[symbol], index, direction, strength, config)
            if not trade:
                continue
            if cost_scale != 1.0:
                trade["net_r"] = round(float(trade["gross_r"]) - cost_scale * float(trade["cost_r"]), 5)
            output.append(trade)
            active_until[symbol] = datetime.fromisoformat(trade["exit_at"])
            used_currencies.update(currencies)
            cards += 1
    return output


def max_drawdown(values: list[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


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


def score(full: dict[str, Any], first: dict[str, Any], second: dict[str, Any]) -> float:
    if full["trades"] < 60:
        return -1000 + full["trades"]
    stability = min(first["avg_r"], second["avg_r"])
    return stability * 5 + full["avg_r"] * 3 + full["coverage_percent"] / 100 - full["max_drawdown_r"] * 0.025


def render_report(payload: dict[str, Any]) -> str:
    meta, champion = payload["metadata"], payload["champion"]
    lines = [
        "# Cross-sectional currency-strength walk-forward", "",
        f"- Data: Yahoo hourly midpoint proxy, {meta['start']} through {meta['end']}, {len(meta['symbols'])} pairs.",
        f"- Chronological split: train through {meta['train_end']}; untouched validation starts {meta['validation_start']}.",
        f"- Search: {meta['configurations']} combinations of momentum/reversal, 1–3 cards, correlation filter, entry hour, stop, RR and hold.",
        "- Execution: signal after an hourly close, next-hour entry, estimated cost, conservative SL on same-bar ambiguity.", "",
        "## Training winner", "",
        f"`{champion['config']}`", "",
        f"- Train: {champion['train']['trades']} trades, {champion['train']['total_r']:.2f}R, avg {champion['train']['avg_r']:.3f}R, PF {champion['train']['profit_factor']:.2f}, coverage {champion['train']['coverage_percent']:.1f}%.",
        f"- Validation: {champion['validation']['trades']} trades, {champion['validation']['total_r']:.2f}R, avg {champion['validation']['avg_r']:.3f}R, PF {champion['validation']['profit_factor']:.2f}, max DD {champion['validation']['max_drawdown_r']:.2f}R, coverage {champion['validation']['coverage_percent']:.1f}%.",
        f"- Double-cost validation: {champion['double_cost']['total_r']:.2f}R, avg {champion['double_cost']['avg_r']:.3f}R.",
        f"- Gate: **{payload['production_gate']['status']}** — {payload['production_gate']['reason']}", "",
        "## Top five selected only on training", "",
        "| Rank | Configuration | Train avg/PF | Validation avg/PF | Validation R |",
        "|---:|---|---:|---:|---:|",
    ]
    for row in payload["top_five"]:
        lines.append(
            f"| {row['rank']} | `{row['config']}` | {row['train']['avg_r']:.3f} / {row['train']['profit_factor']:.2f} | "
            f"{row['validation']['avg_r']:.3f} / {row['validation']['profit_factor']:.2f} | {row['validation']['total_r']:.2f} |"
        )
    lines.extend([
        "", "## Limits", "",
        "- Yahoo prices are indicative, not executable FBS bid/ask quotes.",
        "- This intraday currency-strength formulation is inspired by cross-sectional FX momentum, but it is not the monthly academic portfolio construction.",
        "- Interest-rate carry, macro releases, variable spreads, swaps and rejected orders are not modeled.",
        "- No production setting is changed by this research.", "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=Path("research/.cache/forex-hourly"))
    parser.add_argument("--output-dir", type=Path, default=Path("research/results/forex-currency-strength"))
    args = parser.parse_args()
    raw, errors = {}, {}
    for symbol in SYMBOLS:
        try:
            bars = fetch(symbol, args.cache_dir)
            if len(bars) < 4000:
                raise RuntimeError(f"only {len(bars)} bars")
            raw[symbol] = bars
        except Exception as exc:  # pragma: no cover
            errors[symbol] = str(exc)
        time.sleep(0.2)
    if len(raw) < 10:
        raise SystemExit(f"Insufficient symbols: {errors}")
    data = {symbol: Series(bars) for symbol, bars in raw.items()}
    dates = sorted({bar.timestamp.date() for series in data.values() for bar in series.bars if bar.timestamp.weekday() < 5})
    split_index = int(len(dates) * 0.70)
    train_dates, validation_dates = dates[:split_index], dates[split_index:]
    midpoint = len(train_dates) // 2
    first_dates, second_dates = set(train_dates[:midpoint]), set(train_dates[midpoint:])
    evaluated = []
    for config in configurations():
        rows = simulate(data, config, set(train_dates))
        full = metrics(rows, len(train_dates))
        first = metrics([row for row in rows if datetime.fromisoformat(row["signal_at"]).date() in first_dates], len(first_dates))
        second = metrics([row for row in rows if datetime.fromisoformat(row["signal_at"]).date() in second_dates], len(second_dates))
        evaluated.append({"config": config, "train": full, "first": first, "second": second, "score": score(full, first, second)})
    evaluated.sort(key=lambda row: (row["score"], row["train"]["total_r"]), reverse=True)
    top_five = []
    for rank, row in enumerate(evaluated[:5], start=1):
        validation_rows = simulate(data, row["config"], set(validation_dates))
        top_five.append({
            "rank": rank, "config": row["config"].key, "score": round(row["score"], 5),
            "train": row["train"], "first": row["first"], "second": row["second"],
            "validation": metrics(validation_rows, len(validation_dates)), "validation_rows": validation_rows,
        })
    winner = evaluated[0]
    validation = top_five[0]["validation"]
    double_cost_rows = simulate(data, winner["config"], set(validation_dates), cost_scale=2.0)
    double_cost = metrics(double_cost_rows, len(validation_dates))
    conditions = {
        "at_least_40_validation_trades": validation["trades"] >= 40,
        "coverage_at_least_60pct": validation["coverage_percent"] >= 60,
        "avg_r_at_least_0_08": validation["avg_r"] >= 0.08,
        "profit_factor_at_least_1_20": validation["profit_factor"] >= 1.20,
        "max_drawdown_below_12r": validation["max_drawdown_r"] < 12,
        "positive_at_double_cost": double_cost["total_r"] > 0,
    }
    passed = all(conditions.values())
    failed = [name for name, okay in conditions.items() if not okay]
    payload = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(), "start": dates[0].isoformat(), "end": dates[-1].isoformat(),
            "train_end": train_dates[-1].isoformat(), "validation_start": validation_dates[0].isoformat(),
            "symbols": sorted(data), "download_errors": errors, "configurations": len(evaluated),
        },
        "champion": {
            "config": winner["config"].key, "parameters": asdict(winner["config"]), "train": winner["train"],
            "fold_a": winner["first"], "fold_b": winner["second"], "validation": validation,
            "double_cost": double_cost, "validation_rows": top_five[0]["validation_rows"],
        },
        "top_five": top_five,
        "production_gate": {
            "status": "PASS — candidate for independent demo forward test" if passed else "FAIL — do not deploy",
            "conditions": conditions,
            "reason": "All robustness conditions passed." if passed else "Failed: " + ", ".join(failed),
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "report.md").write_text(render_report(payload))
    print(json.dumps({
        "report": str(args.output_dir / "report.md"), "symbols": len(data), "errors": errors,
        "configurations": len(evaluated), "champion": winner["config"].key,
        "train": winner["train"], "validation": validation, "double_cost": double_cost,
        "gate": payload["production_gate"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
