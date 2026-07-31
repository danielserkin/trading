#!/usr/bin/env python3
"""Backtest the intraday scanner over recent Binance proxy candles."""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fetch_binance_market import _regime_blocks_setup, _select_setup, atr, fmean, rsi, rr, sma
from run_crypto_web_session import build_universe, fetch_fear_greed


BASE_URL = "https://api.binance.com"
INTERVAL_MS = {
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
}


def get_json(path: str, params: dict[str, Any]) -> Any:
    query = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{BASE_URL}{path}?{query}", timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_klines(symbol: str, interval: str, start: datetime, end: datetime) -> list[list[Any]]:
    rows: list[list[Any]] = []
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    step = INTERVAL_MS[interval]
    while start_ms < end_ms:
        chunk = get_json(
            "/api/v3/klines",
            {
                "symbol": symbol,
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 1000,
            },
        )
        if not chunk:
            break
        rows.extend(chunk)
        next_start = int(chunk[-1][0]) + step
        if next_start <= start_ms:
            break
        start_ms = next_start
        time.sleep(0.03)
    return rows


def rows_until(rows: list[list[Any]], as_of_ms: int) -> list[list[Any]]:
    return [row for row in rows if int(row[6]) <= as_of_ms]


def rows_between(rows: list[list[Any]], start_ms: int, end_ms: int) -> list[list[Any]]:
    return [row for row in rows if start_ms <= int(row[0]) <= end_ms]


def candidate_from_rows(
    symbol: str,
    broker_symbol: str,
    rows_15m: list[list[Any]],
    rows_1h: list[list[Any]],
    rows_4h: list[list[Any]],
    as_of: datetime,
    regime: str,
    min_quote_volume_usd: float,
    min_rr: float,
) -> dict[str, Any] | None:
    as_of_ms = int(as_of.timestamp() * 1000)
    closed = rows_until(rows_15m, as_of_ms)[-96:]
    closed_1h = rows_until(rows_1h, as_of_ms)[-80:]
    closed_4h = rows_until(rows_4h, as_of_ms)[-80:]
    if len(closed) < 50 or len(closed_1h) < 50 or len(closed_4h) < 50:
        return None

    quote_volume = sum(float(row[7]) for row in closed[-96:])
    if quote_volume < min_quote_volume_usd:
        return None

    closes = [float(row[4]) for row in closed]
    closes_1h = [float(row[4]) for row in closed_1h]
    closes_4h = [float(row[4]) for row in closed_4h]
    current = closes[-1]
    volatility = atr(closed)
    if volatility <= 0:
        return None

    highs_20 = [float(row[2]) for row in closed[-20:]]
    lows_20 = [float(row[3]) for row in closed[-20:]]
    recent_high = max(highs_20)
    recent_low = min(lows_20)
    previous_volumes = [float(row[5]) for row in closed[-21:-1]]
    volume_ratio = float(closed[-1][5]) / fmean(previous_volumes) if previous_volumes else 0.0
    range_position = (current - recent_low) / (recent_high - recent_low) if recent_high > recent_low else 0.5

    rsi_15m = rsi(closes)
    rsi_1h = rsi(closes_1h)
    rsi_4h = rsi(closes_4h)
    setup = _select_setup(
        current=current,
        fast=sma(closes, 12),
        slow=sma(closes, 30),
        fast_1h=sma(closes_1h, 20),
        slow_1h=sma(closes_1h, 50),
        fast_4h=sma(closes_4h, 20),
        slow_4h=sma(closes_4h, 50),
        rsi_15m=rsi_15m,
        rsi_1h=rsi_1h,
        rsi_4h=rsi_4h,
        volume_ratio=volume_ratio,
        range_position=range_position,
        recent_high=recent_high,
        recent_low=recent_low,
        volatility=volatility,
        min_rr=min_rr,
    )
    if setup is None or _regime_blocks_setup(setup["direction"], setup["setup_type"], regime):
        return None

    stop_loss = float(setup["stop_loss"])
    take_profit = float(setup["take_profit"])
    risk_reward = rr(current, stop_loss, take_profit)
    if risk_reward < min_rr:
        return None

    return {
        "asset": broker_symbol,
        "market_symbol": symbol,
        "direction": setup["direction"],
        "entry": current,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_reward": risk_reward,
        "setup_type": setup["setup_type"],
        "execution_bias": setup["execution_bias"],
        "as_of": as_of.isoformat(),
        "closed_candle_time": datetime.fromtimestamp(int(closed[-1][6]) / 1000, tz=timezone.utc).isoformat(),
        "rsi_15m": rsi_15m,
        "rsi_1h": rsi_1h,
        "rsi_4h": rsi_4h,
        "volume_ratio": volume_ratio,
        "range_position": range_position,
    }


def evaluate(candidate: dict[str, Any], rows_15m: list[list[Any]], as_of: datetime, horizon_hours: int) -> dict[str, Any]:
    start_ms = int(as_of.timestamp() * 1000)
    end_ms = int((as_of + timedelta(hours=horizon_hours)).timestamp() * 1000)
    rows = rows_between(rows_15m, start_ms, end_ms)
    direction = candidate["direction"]
    stop_loss = float(candidate["stop_loss"])
    take_profit = float(candidate["take_profit"])
    entry = float(candidate["entry"])
    risk = abs(entry - stop_loss)
    last_close = entry

    for row in rows:
        high = float(row[2])
        low = float(row[3])
        last_close = float(row[4])
        hit_tp = high >= take_profit if direction == "BUY" else low <= take_profit
        hit_sl = low <= stop_loss if direction == "BUY" else high >= stop_loss
        hit_time = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc).isoformat()
        if hit_tp and hit_sl:
            return {"result": "ambiguous", "r_multiple": 0.0, "time": hit_time}
        if hit_tp:
            return {"result": "tp", "r_multiple": float(candidate["risk_reward"]), "time": hit_time}
        if hit_sl:
            return {"result": "sl", "r_multiple": -1.0, "time": hit_time}

    if risk == 0:
        mark_r = 0.0
    elif direction == "BUY":
        mark_r = (last_close - entry) / risk
    else:
        mark_r = (entry - last_close) / risk
    return {"result": "timeout", "r_multiple": max(-1.0, min(float(candidate["risk_reward"]), mark_r)), "time": None}


def summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = defaultdict(lambda: {"trades": 0, "tp": 0, "sl": 0, "timeout": 0, "ambiguous": 0, "r": 0.0})
    for trade in trades:
        for key in ("all", f"setup:{trade['setup_type']}", f"asset:{trade['asset']}", f"direction:{trade['direction']}"):
            group = groups[key]
            result = trade["outcome"]["result"]
            group["trades"] += 1
            group[result] += 1
            group["r"] += float(trade["outcome"]["r_multiple"])
    for group in groups.values():
        trades_count = group["trades"]
        group["win_rate"] = round(group["tp"] / trades_count * 100, 2) if trades_count else 0
        group["avg_r"] = round(group["r"] / trades_count, 4) if trades_count else 0
        group["total_r"] = round(group["r"], 4)
    return dict(sorted(groups.items()))


def render_markdown(summary: dict[str, Any], trades: list[dict[str, Any]], metadata: dict[str, Any]) -> str:
    all_stats = summary.get("all", {})
    lines = [
        f"# Intraday Scanner Backtest - {metadata['generated_at'][:10]}",
        "",
        "## Summary",
        "",
        f"- Period: {metadata['start']} to {metadata['end']}",
        f"- Scan step: every {metadata['step_hours']}h",
        f"- Outcome horizon: {metadata['horizon_hours']}h",
        f"- Symbols scanned: {metadata['symbols_scanned']}",
        f"- Trades: {all_stats.get('trades', 0)}",
        f"- TP: {all_stats.get('tp', 0)}",
        f"- SL: {all_stats.get('sl', 0)}",
        f"- Timeout: {all_stats.get('timeout', 0)}",
        f"- Ambiguous same-candle: {all_stats.get('ambiguous', 0)}",
        f"- Win rate: {all_stats.get('win_rate', 0)}%",
        f"- Total R: {all_stats.get('total_r', 0)}",
        f"- Avg R/trade: {all_stats.get('avg_r', 0)}",
        "",
        "## Conclusions",
        "",
        *conclusions(summary),
        "",
        "## Breakdown",
        "",
        "| Group | Trades | TP | SL | Timeout | Ambiguous | Win Rate | Total R | Avg R |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for key, stats in summary.items():
        lines.append(
            f"| {key} | {stats['trades']} | {stats['tp']} | {stats['sl']} | {stats['timeout']} | {stats['ambiguous']} | {stats['win_rate']}% | {stats['total_r']} | {stats['avg_r']} |"
        )
    lines.extend([
        "",
        "## Trades",
        "",
        "| As Of | Asset | Direction | Setup | Entry | SL | TP | Result | R | Time |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for trade in trades:
        outcome = trade["outcome"]
        lines.append(
            "| {as_of} | {asset} | {direction} | {setup} | {entry:.8g} | {sl:.8g} | {tp:.8g} | {result} | {r:.2f} | {time} |".format(
                as_of=trade["as_of"],
                asset=trade["asset"],
                direction=trade["direction"],
                setup=trade["setup_type"],
                entry=float(trade["entry"]),
                sl=float(trade["stop_loss"]),
                tp=float(trade["take_profit"]),
                result=outcome["result"],
                r=float(outcome["r_multiple"]),
                time=outcome.get("time") or "",
            )
        )
    lines.extend([
        "",
        "## Limits",
        "",
        "- Binance spot candles are only a proxy for FBS crypto CFDs.",
        "- Historical bid/ask spread and real fills are not modeled.",
        "- Current CoinGecko universe and current Fear & Greed are used as context; this is not a fully point-in-time dataset.",
        "- Overlapping signals on the same asset are de-duplicated while a prior signal is still inside its outcome horizon.",
    ])
    return "\n".join(lines) + "\n"


def conclusions(summary: dict[str, Any]) -> list[str]:
    all_stats = summary.get("all", {})
    trades = int(all_stats.get("trades", 0))
    avg_r = float(all_stats.get("avg_r", 0))
    win_rate = float(all_stats.get("win_rate", 0))
    if trades < 20:
        sample = "- Sample is too small for a reliable trading conclusion."
    elif avg_r <= 0:
        sample = "- Current rules do not show positive expectancy in this sample."
    else:
        sample = "- Current rules show positive expectancy in this sample, but need a larger out-of-sample check."
    frequency = "- Signal frequency is low; this behaves like a selective filter, not a high-activity strategy." if trades < 10 else "- Signal frequency is usable for monitoring, but still sparse."
    quality = f"- Observed win rate is {win_rate:.2f}% with average {avg_r:.4f}R per trade."
    return [sample, frequency, quality]


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest the intraday scanner on recent public Binance proxy candles.")
    parser.add_argument("--config-dir", type=Path, default=Path("config"))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--horizon-hours", type=int, default=8)
    parser.add_argument("--max-symbols", type=int, default=60)
    parser.add_argument("--min-quote-volume-usd", type=float, default=10_000_000)
    parser.add_argument("--min-rr", type=float, default=1.6)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)
    fetch_start = start - timedelta(days=20)
    symbols, context_by_symbol, universe_metadata = build_universe(args.config_dir, 80, [], "fbs")
    symbols = symbols[: args.max_symbols]
    fear_greed = fetch_fear_greed()
    regime = fear_greed["regime"]

    market_data = {}
    for symbol in symbols:
        market_data[symbol] = {
            "15m": fetch_klines(symbol, "15m", fetch_start, end + timedelta(hours=args.horizon_hours)),
            "1h": fetch_klines(symbol, "1h", fetch_start, end),
            "4h": fetch_klines(symbol, "4h", fetch_start, end),
        }

    trades: list[dict[str, Any]] = []
    active_until_by_symbol: dict[str, datetime] = {}
    as_of = start
    while as_of <= end:
        for symbol in symbols:
            if active_until_by_symbol.get(symbol, start) > as_of:
                continue
            context = context_by_symbol.get(symbol, {})
            candidate = candidate_from_rows(
                symbol,
                str(context.get("broker_symbol", symbol)),
                market_data[symbol]["15m"],
                market_data[symbol]["1h"],
                market_data[symbol]["4h"],
                as_of,
                regime,
                args.min_quote_volume_usd,
                args.min_rr,
            )
            if not candidate:
                continue
            outcome = evaluate(candidate, market_data[symbol]["15m"], as_of, args.horizon_hours)
            candidate["outcome"] = outcome
            trades.append(candidate)
            active_until_by_symbol[symbol] = as_of + timedelta(hours=args.horizon_hours)
        as_of += timedelta(hours=args.step_hours)

    summary = summarize(trades)
    generated_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "generated_at": generated_at,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": args.days,
        "step_hours": args.step_hours,
        "horizon_hours": args.horizon_hours,
        "symbols_scanned": len(symbols),
        "universe": universe_metadata,
        "fear_greed_current": fear_greed,
    }

    output_dir = args.output_dir or Path("sessions") / end.date().isoformat() / f"backtest-{args.days}d-{args.horizon_hours}h"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "trades.json").write_text(json.dumps(trades, indent=2, sort_keys=True) + "\n")
    (output_dir / "summary.json").write_text(json.dumps({"metadata": metadata, "summary": summary}, indent=2, sort_keys=True) + "\n")
    (output_dir / "backtest-report.md").write_text(render_markdown(summary, trades, metadata))
    print(json.dumps({"report": str(output_dir / "backtest-report.md"), "trades": len(trades), "summary": summary.get("all", {})}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
