#!/usr/bin/env python3
"""Point-in-time backtest of Telegram signals captured by trading sessions.

The script deduplicates messages, rejects structurally invalid calls and result
updates, enters no earlier than the first complete 15-minute bar after the
publication timestamp, and selects any rule only on the chronological training
slice.  The later slice is reported untouched.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import re
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
CURRENT_PROVIDERS = {
    "pipxpert", "forexvisitsignals", "unitedsignalsfx", "gold_signals",
    "nasgold1", "learn2tradenews",
}
MANUAL_TICKERS = {
    "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD", "NATGAS": "NG=F",
    "NIO": "NIO", "UAL": "UAL", "TSLA": "TSLA", "AAPL": "AAPL",
    "US30": "YM=F", "US100": "NQ=F", "US500": "ES=F",
    "XAUA": "CL=FA",
}
UPDATE_RE = re.compile(
    r"(?is)(?:\b(?:tp|take profit|target)\s*\d*\b.{0,24}\b(?:hit|achieved|reached)\b"
    r"|\b(?:trade|vip)\s+update\b|\bclosed\b.{0,20}\b(?:profit|gain)\b"
    r"|\brunning\s*.{0,8}\+\s*\d)",
)


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Signal:
    provider: str
    message_id: str
    timestamp: datetime
    asset: str
    ticker: str
    direction: str
    entry: float
    stop: float
    target: float
    offered_rr: float
    max_age_hours: float


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc)


def ticker_for(row: dict[str, Any], asset: str) -> str | None:
    ticker = row.get("market_symbol")
    if isinstance(ticker, str) and ticker:
        return ticker
    if asset in MANUAL_TICKERS:
        return MANUAL_TICKERS[asset]
    if len(asset) == 6 and asset.isalpha():
        return f"{asset}=X"
    return None


def load_signals(session_root: Path) -> tuple[list[Signal], dict[str, int]]:
    files = sorted(session_root.glob("**/telegram-fbs-candidates.json"))
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    raw_rows = 0
    for path in files:
        try:
            rows = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rows, list):
            continue
        raw_rows += len(rows)
        for row in rows:
            if not isinstance(row, dict):
                continue
            provider = str(row.get("channel") or row.get("provider") or "").lower()
            message_id = row.get("message_id")
            if not provider or message_id is None:
                continue
            unique.setdefault((provider, str(message_id)), row)

    rejected = defaultdict(int)
    signals: list[Signal] = []
    for (provider, message_id), row in unique.items():
        direction = str(row.get("direction") or "").upper()
        entry = finite_number(row.get("entry"))
        stop = finite_number(row.get("stop_loss"))
        timestamp = parse_timestamp(row.get("timestamp"))
        asset = str(row.get("asset") or "").upper()
        targets = [finite_number(item) for item in (row.get("take_profits") or [])]
        if direction not in {"BUY", "SELL"} or entry is None or stop is None or timestamp is None or not asset:
            rejected["incomplete"] += 1
            continue
        if UPDATE_RE.search(str(row.get("raw_text") or "")):
            rejected["outcome_update"] += 1
            continue
        structural = stop < entry if direction == "BUY" else stop > entry
        if not structural:
            rejected["invalid_stop"] += 1
            continue
        favorable = [
            value for value in targets if value is not None and
            ((direction == "BUY" and value > entry) or (direction == "SELL" and value < entry))
        ]
        if not favorable:
            rejected["invalid_target"] += 1
            continue
        target = min(favorable) if direction == "BUY" else max(favorable)
        risk = abs(entry - stop)
        offered_rr = abs(target - entry) / risk
        if risk <= 0 or not 0.05 <= offered_rr <= 8:
            rejected["implausible_rr"] += 1
            continue
        ticker = ticker_for(row, asset)
        if not ticker:
            rejected["no_market_proxy"] += 1
            continue
        max_age = finite_number(row.get("max_age_hours")) or 12.0
        signals.append(Signal(
            provider=provider, message_id=message_id, timestamp=timestamp,
            asset=asset, ticker=ticker, direction=direction, entry=entry,
            stop=stop, target=target, offered_rr=offered_rr,
            max_age_hours=min(max(max_age, 1.0), 24.0),
        ))
    signals.sort(key=lambda item: (item.timestamp, item.provider, item.message_id))
    audit = {
        "files": len(files), "raw_rows": raw_rows, "unique_messages": len(unique),
        "structurally_executable": len(signals), **dict(sorted(rejected.items())),
    }
    return signals, audit


def cached_forex_path(cache_dir: Path, ticker: str) -> Path | None:
    if not ticker.endswith("=X"):
        return None
    candidate = cache_dir / f"{ticker[:-2]}-60d-15m.json"
    return candidate if candidate.exists() else None


def fetch_bars(ticker: str, cache_dir: Path) -> list[Bar]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_name = urllib.parse.quote(ticker, safe="").replace("%", "_")
    cache_path = cache_dir / f"ticker-{safe_name}-60d-15m.json"
    legacy = cached_forex_path(cache_dir, ticker)
    source = cache_path if cache_path.exists() else legacy
    if source:
        payload = json.loads(source.read_text())
    else:
        encoded = urllib.parse.quote(ticker, safe="")
        query = urllib.parse.urlencode({"range": "60d", "interval": "15m", "includePrePost": "true"})
        request = urllib.request.Request(
            f"{YAHOO_URL}/{encoded}?{query}",
            headers={"User-Agent": "Mozilla/5.0 telegram-signal-research/1.0"},
        )
        error: Exception | None = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                cache_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
                break
            except Exception as exc:  # pragma: no cover - network behavior
                error = exc
                time.sleep(2.0 * (attempt + 1))
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
    bars: list[Bar] = []
    for index, stamp in enumerate(timestamps):
        values = [quote.get(key, [None] * len(timestamps))[index] for key in ("open", "high", "low", "close")]
        if any(value is None for value in values):
            continue
        bars.append(Bar(
            datetime.fromtimestamp(int(stamp), tz=timezone.utc),
            *[float(value) for value in values],
        ))
    return sorted(bars, key=lambda bar: bar.timestamp)


def all_in_cost(asset: str, price: float) -> float:
    if len(asset) == 6 and asset.isalpha() and asset not in {"XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD"}:
        pip = 0.01 if asset.endswith("JPY") else 0.0001
        return 1.4 * pip
    if asset == "XAUUSD":
        return 0.55
    if asset == "XAGUSD":
        return 0.035
    if asset in {"BTCUSD", "ETHUSD"}:
        return 0.0012 * price
    if asset in {"US30", "US100", "US500"}:
        return max(0.8, 0.00012 * price)
    if asset in {"USOIL", "NATGAS"}:
        return 0.04
    return max(0.02, 0.0002 * price)


def compatible_gap(asset: str, entry: float, risk: float) -> float:
    fraction = 0.006 if len(asset) == 6 and asset.isalpha() and asset not in {"XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD"} else 0.025
    return max(3.0 * risk, fraction * entry)


def evaluate_signal(signal: Signal, bars: list[Bar], horizon_hours: float) -> dict[str, Any]:
    timestamps = [bar.timestamp for bar in bars]
    start_index = bisect.bisect_right(timestamps, signal.timestamp)
    base = {**asdict(signal), "timestamp": signal.timestamp.isoformat(), "horizon_hours": horizon_hours}
    if start_index >= len(bars):
        return {**base, "status": "no_data", "net_r": None}
    first = bars[start_index]
    risk_at_call = abs(signal.entry - signal.stop)
    if abs(first.open - signal.entry) > compatible_gap(signal.asset, signal.entry, risk_at_call):
        return {**base, "status": "proxy_mismatch", "net_r": None}

    expires = signal.timestamp + timedelta(hours=signal.max_age_hours)
    fill_index: int | None = None
    fill_price: float | None = None
    near_market = max(0.12 * risk_at_call, 2.5 * all_in_cost(signal.asset, signal.entry))
    if abs(first.open - signal.entry) <= near_market:
        fill_index, fill_price = start_index, first.open
    else:
        for index in range(start_index, len(bars)):
            bar = bars[index]
            if bar.timestamp > expires:
                break
            if bar.low <= signal.entry <= bar.high:
                fill_index, fill_price = index, signal.entry
                break
    if fill_index is None or fill_price is None:
        return {**base, "status": "not_filled", "net_r": None}

    risk = (fill_price - signal.stop) if signal.direction == "BUY" else (signal.stop - fill_price)
    reward = (signal.target - fill_price) if signal.direction == "BUY" else (fill_price - signal.target)
    if risk <= 0 or reward <= 0:
        return {**base, "status": "invalid_after_gap", "net_r": None}
    cost_r = all_in_cost(signal.asset, fill_price) / risk
    exit_deadline = bars[fill_index].timestamp + timedelta(hours=horizon_hours)
    exit_price = bars[fill_index].close
    outcome = "time_exit"
    exit_at = bars[fill_index].timestamp
    for bar in bars[fill_index:]:
        if bar.timestamp > exit_deadline:
            break
        stop_hit = bar.low <= signal.stop if signal.direction == "BUY" else bar.high >= signal.stop
        target_hit = bar.high >= signal.target if signal.direction == "BUY" else bar.low <= signal.target
        if stop_hit:  # Conservative ordering when both levels occur in one candle.
            outcome, exit_price, exit_at = "stop", signal.stop, bar.timestamp
            break
        if target_hit:
            outcome, exit_price, exit_at = "target", signal.target, bar.timestamp
            break
        exit_price, exit_at = bar.close, bar.timestamp
    gross_r = ((exit_price - fill_price) if signal.direction == "BUY" else (fill_price - exit_price)) / risk
    return {
        **base, "status": outcome, "filled_at": bars[fill_index].timestamp.isoformat(),
        "fill_price": round(fill_price, 8), "exit_at": exit_at.isoformat(),
        "gross_r": round(gross_r, 5), "cost_r": round(cost_r, 5),
        "net_r": round(gross_r - cost_r, 5),
    }


def max_drawdown(values: list[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def metrics(rows: list[dict[str, Any]], period_dates: list[date]) -> dict[str, Any]:
    fills = [row for row in rows if row.get("net_r") is not None]
    values = [float(row["net_r"]) for row in fills]
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    signal_days = {str(row["timestamp"])[:10] for row in rows}
    fill_days = {str(row["filled_at"])[:10] for row in fills}
    return {
        "signals": len(rows), "fills": len(fills),
        "fill_rate_percent": round(100 * len(fills) / len(rows), 2) if rows else 0.0,
        "targets": sum(row.get("status") == "target" for row in fills),
        "stops": sum(row.get("status") == "stop" for row in fills),
        "time_exits": sum(row.get("status") == "time_exit" for row in fills),
        "total_r": round(sum(values), 4),
        "avg_r": round(statistics.mean(values), 4) if values else 0.0,
        "profit_factor": round(gains / losses, 3) if losses else (999.0 if gains else 0.0),
        "max_drawdown_r": round(max_drawdown(values), 4),
        "signal_day_coverage_percent": round(100 * len(signal_days) / len(period_dates), 2) if period_dates else 0.0,
        "fill_day_coverage_percent": round(100 * len(fill_days) / len(period_dates), 2) if period_dates else 0.0,
    }


def is_duplicate(candidate: dict[str, Any], accepted: list[dict[str, Any]]) -> bool:
    stamp = datetime.fromisoformat(candidate["timestamp"])
    for prior in reversed(accepted):
        prior_stamp = datetime.fromisoformat(prior["timestamp"])
        if stamp - prior_stamp > timedelta(minutes=45):
            break
        if candidate["asset"] != prior["asset"] or candidate["direction"] != prior["direction"]:
            continue
        scale = max(abs(float(candidate["entry"]) - float(candidate["stop"])), 1e-12)
        if abs(float(candidate["entry"]) - float(prior["entry"])) <= 0.35 * scale:
            return True
    return False


def apply_rule(
    rows: list[dict[str, Any]], rule: dict[str, Any], provider_scores: dict[str, float],
    max_daily: int = 3,
) -> list[dict[str, Any]]:
    eligible = []
    for row in rows:
        if row["provider"] not in rule["providers"] or float(row["offered_rr"]) < rule["min_rr"]:
            continue
        if rule["market"] == "forex" and not (len(row["asset"]) == 6 and row["asset"].isalpha() and row["asset"] not in {"XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD"}):
            continue
        if rule["market"] == "gold" and row["asset"] != "XAUUSD":
            continue
        if rule["hours"] == "liquid" and datetime.fromisoformat(row["timestamp"]).hour not in range(6, 17):
            continue
        eligible.append(row)
    eligible.sort(key=lambda row: (
        row["timestamp"][:10], row["timestamp"], -provider_scores.get(row["provider"], -999), row["provider"],
    ))
    accepted: list[dict[str, Any]] = []
    daily = defaultdict(int)
    for row in eligible:
        day = row["timestamp"][:10]
        if daily[day] >= max_daily or is_duplicate(row, accepted):
            continue
        accepted.append(row)
        daily[day] += 1
    return accepted


def calendar_dates(start: date, end: date) -> list[date]:
    result = []
    cursor = start
    while cursor <= end:
        result.append(cursor)
        cursor += timedelta(days=1)
    return result


def render_report(payload: dict[str, Any]) -> str:
    meta, audit = payload["metadata"], payload["audit"]
    lines = [
        "# Telegram provider walk-forward", "",
        f"- Captures: {audit['files']} files, {audit['raw_rows']} repeated rows, {audit['unique_messages']} unique messages.",
        f"- Structurally testable after conservative cleanup: {audit['structurally_executable']}.",
        f"- Price proxy: Yahoo 15-minute data; period {meta['start']} through {meta['end']}.",
        f"- Selection slice ends {meta['train_end']}; untouched validation starts {meta['test_start']}.",
        "- Execution: first complete bar after publication, stated entry or near-market next open, all-in cost estimate, stop wins same-bar ambiguity.",
        "", "## Current providers", "",
        "| Provider | Complete | 12h train fills / R | 12h validation fills / R | Validation PF |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in payload["current_provider_table"]:
        lines.append(
            f"| {row['provider']} | {row['complete']} | {row['train']['fills']} / {row['train']['total_r']:.2f} | "
            f"{row['validation']['fills']} / {row['validation']['total_r']:.2f} | {row['validation']['profit_factor']:.2f} |"
        )
    lines.extend(["", "## Rules selected without validation hindsight", ""])
    for item in payload["horizon_results"]:
        selected = item["selected"]
        lines.extend([
            f"### {item['horizon_hours']} hour exit", "",
            f"Selected on training: `{selected['name']}`.", "",
            f"- Training: {selected['train']['signals']} signals, {selected['train']['fills']} fills, "
            f"{selected['train']['total_r']:.2f}R, avg {selected['train']['avg_r']:.3f}R, PF {selected['train']['profit_factor']:.2f}.",
            f"- Validation: {selected['validation']['signals']} signals, {selected['validation']['fills']} fills, "
            f"{selected['validation']['total_r']:.2f}R, avg {selected['validation']['avg_r']:.3f}R, "
            f"PF {selected['validation']['profit_factor']:.2f}, signal-day coverage {selected['validation']['signal_day_coverage_percent']:.1f}%.",
            f"- Gate: **{item['gate']['status']}** — {item['gate']['reason']}", "",
        ])
    lines.extend([
        "## Disabled-provider diagnostic", "",
        "This table uses a separate chronological split inside each provider. It can nominate channels to recapture, but cannot authorize production because most stopped producing captured messages before the global validation period.", "",
        "| Provider | Fills | Earlier R | Later R | Later PF | Diagnostic |",
        "|---|---:|---:|---:|---:|---|",
    ])
    for row in payload["all_provider_internal_table"]:
        lines.append(
            f"| {row['provider']} | {row['total_fills']} | {row['train']['total_r']:.2f} | "
            f"{row['validation']['total_r']:.2f} | {row['validation']['profit_factor']:.2f} | {row['diagnostic']} |"
        )
    lines.extend([
        "## Interpretation", "",
        payload["interpretation"], "",
        "This is research, not a production configuration change. Proxy/broker basis differences, Telegram parsing errors, deleted messages, and the short capture window remain material limitations.", "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=Path, default=Path("sessions"))
    parser.add_argument("--cache-dir", type=Path, default=Path("research/.cache/forex"))
    parser.add_argument("--output-dir", type=Path, default=Path("research/results/telegram-provider-walk-forward"))
    args = parser.parse_args()

    signals, audit = load_signals(args.sessions)
    tickers = sorted({signal.ticker for signal in signals})
    market_data: dict[str, list[Bar]] = {}
    errors: dict[str, str] = {}
    for ticker in tickers:
        try:
            bars = fetch_bars(ticker, args.cache_dir)
            if bars:
                market_data[ticker] = bars
        except Exception as exc:  # pragma: no cover - network behavior
            errors[ticker] = str(exc)
        time.sleep(0.15)

    usable = [signal for signal in signals if signal.ticker in market_data]
    if not usable:
        raise SystemExit("No signals have market data")
    dates = sorted({signal.timestamp.date() for signal in usable})
    split_index = max(1, min(len(dates) - 1, int(len(dates) * 0.65)))
    train_end, test_start = dates[split_index - 1], dates[split_index]
    start, end = dates[0], dates[-1]
    train_dates = calendar_dates(start, train_end)
    test_dates = calendar_dates(test_start, end)

    all_evaluated: dict[float, list[dict[str, Any]]] = {}
    for horizon in (4.0, 12.0, 24.0):
        all_evaluated[horizon] = [evaluate_signal(signal, market_data[signal.ticker], horizon) for signal in usable]

    primary = all_evaluated[12.0]
    current_provider_table = []
    provider_scores: dict[str, float] = {}
    for provider in sorted(CURRENT_PROVIDERS):
        provider_rows = [row for row in primary if row["provider"] == provider]
        train = metrics([row for row in provider_rows if str(row["timestamp"])[:10] <= train_end.isoformat()], train_dates)
        validation = metrics([row for row in provider_rows if str(row["timestamp"])[:10] >= test_start.isoformat()], test_dates)
        provider_scores[provider] = train["avg_r"] if train["fills"] >= 5 else -999.0
        current_provider_table.append({"provider": provider, "complete": len(provider_rows), "train": train, "validation": validation})
    current_provider_table.sort(key=lambda row: (-row["train"]["avg_r"], row["provider"]))

    all_provider_internal_table = []
    for provider in sorted({row["provider"] for row in primary}):
        provider_rows = sorted(
            [row for row in primary if row["provider"] == provider],
            key=lambda row: row["timestamp"],
        )
        provider_signal_dates = sorted({str(row["timestamp"])[:10] for row in provider_rows})
        if len(provider_signal_dates) < 2:
            continue
        internal_index = max(1, min(len(provider_signal_dates) - 1, int(len(provider_signal_dates) * 0.65)))
        internal_test_start = provider_signal_dates[internal_index]
        early = [row for row in provider_rows if str(row["timestamp"])[:10] < internal_test_start]
        later = [row for row in provider_rows if str(row["timestamp"])[:10] >= internal_test_start]
        early_dates = calendar_dates(datetime.fromisoformat(provider_signal_dates[0]).date(), datetime.fromisoformat(provider_signal_dates[internal_index - 1]).date())
        later_dates = calendar_dates(datetime.fromisoformat(internal_test_start).date(), datetime.fromisoformat(provider_signal_dates[-1]).date())
        early_metric, later_metric = metrics(early, early_dates), metrics(later, later_dates)
        total_fills = early_metric["fills"] + later_metric["fills"]
        if total_fills < 6:
            diagnostic = "insufficient sample"
        elif early_metric["avg_r"] > 0.05 and later_metric["avg_r"] > 0.05 and later_metric["profit_factor"] > 1.15:
            diagnostic = "recapture candidate"
        else:
            diagnostic = "unstable/negative"
        all_provider_internal_table.append({
            "provider": provider, "current": provider in CURRENT_PROVIDERS,
            "test_start": internal_test_start, "total_fills": total_fills,
            "train": early_metric, "validation": later_metric, "diagnostic": diagnostic,
        })
    all_provider_internal_table.sort(key=lambda row: (
        row["diagnostic"] != "recapture candidate", -row["validation"]["avg_r"], -row["total_fills"], row["provider"],
    ))

    rule_templates = []
    for min_rr in (0.0, 0.5, 1.0, 1.3, 1.6, 2.0):
        for market in ("all", "forex", "gold"):
            for hours in ("all", "liquid"):
                rule_templates.append({
                    "name": f"current|minRR={min_rr:g}|market={market}|hours={hours}",
                    "providers": sorted(CURRENT_PROVIDERS), "min_rr": min_rr,
                    "market": market, "hours": hours,
                })

    horizon_results = []
    for horizon, rows in all_evaluated.items():
        train_rows = [row for row in rows if str(row["timestamp"])[:10] <= train_end.isoformat()]
        validation_rows = [row for row in rows if str(row["timestamp"])[:10] >= test_start.isoformat()]
        evaluated_rules = []
        for rule in rule_templates:
            selected_train = apply_rule(train_rows, rule, provider_scores)
            train_metric = metrics(selected_train, train_dates)
            # Penalize tiny samples before looking at return.
            score = -999.0 if train_metric["fills"] < 12 else (
                train_metric["avg_r"] + min(train_metric["profit_factor"], 3.0) * 0.04
                - train_metric["max_drawdown_r"] * 0.003
            )
            evaluated_rules.append((score, train_metric["total_r"], rule, train_metric))
        evaluated_rules.sort(key=lambda item: (item[0], item[1]), reverse=True)
        _, _, winner, train_metric = evaluated_rules[0]
        selected_validation = apply_rule(validation_rows, winner, provider_scores)
        validation_metric = metrics(selected_validation, test_dates)
        conditions = {
            "at_least_10_validation_fills": validation_metric["fills"] >= 10,
            "avg_r_above_0_05": validation_metric["avg_r"] > 0.05,
            "profit_factor_above_1_15": validation_metric["profit_factor"] > 1.15,
            "drawdown_below_8r": validation_metric["max_drawdown_r"] < 8.0,
            "at_least_35pct_signal_days": validation_metric["signal_day_coverage_percent"] >= 35,
        }
        passed = all(conditions.values())
        failures = [name for name, okay in conditions.items() if not okay]
        horizon_results.append({
            "horizon_hours": horizon,
            "selected": {"name": winner["name"], "rule": winner, "train": train_metric, "validation": validation_metric,
                         "validation_rows": selected_validation},
            "training_top_five": [
                {"name": rule["name"], "score": round(score, 5), "train": result}
                for score, _, rule, result in evaluated_rules[:5]
            ],
            "gate": {
                "status": "PASS — candidate for a separate demo forward test" if passed else "FAIL — do not deploy",
                "conditions": conditions,
                "reason": "All conditions passed." if passed else "Failed: " + ", ".join(failures),
            },
        })

    passed_horizons = [item for item in horizon_results if item["gate"]["status"].startswith("PASS")]
    interpretation = (
        "At least one preselected provider/filter rule remained positive in the later period; it still requires an independent demo forward test because the provider history is short."
        if passed_horizons else
        "No provider/filter/horizon combination selected on the earlier messages met the later-period gate. More cards or a longer hold did not create a robust edge from these sources."
    )
    payload = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(), "start": start.isoformat(), "end": end.isoformat(),
            "train_end": train_end.isoformat(), "test_start": test_start.isoformat(),
            "tickers_requested": tickers, "tickers_loaded": sorted(market_data), "download_errors": errors,
            "current_providers": sorted(CURRENT_PROVIDERS),
        },
        "audit": audit, "current_provider_table": current_provider_table,
        "all_provider_internal_table": all_provider_internal_table,
        "horizon_results": horizon_results, "interpretation": interpretation,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "report.md").write_text(render_report(payload))
    print(json.dumps({
        "report": str(args.output_dir / "report.md"), "audit": audit,
        "market_data": {"loaded": len(market_data), "errors": errors},
        "split": {"train_end": train_end.isoformat(), "test_start": test_start.isoformat()},
        "horizons": [
            {"hours": item["horizon_hours"], "rule": item["selected"]["name"],
             "train": item["selected"]["train"], "validation": item["selected"]["validation"],
             "gate": item["gate"]["status"]}
            for item in horizon_results
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
