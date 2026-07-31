#!/usr/bin/env python3
"""Replay an intraday crypto session from an earlier as-of time.

This is a research helper: it builds candidates using only candles closed before
the selected as-of time, then checks whether TP or SL was touched first after it.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fetch_binance_market import (
    _regime_blocks_setup,
    _select_setup,
    atr,
    fmean,
    get_json,
    rsi,
    rr,
    sma,
)
from run_crypto_web_session import (
    build_universe,
    enrich_candidate,
    fetch_fear_greed,
    regime_alignment,
    session_params,
)
from score_candidates import render_report


def parse_as_of(value: str | None, hours_ago: float) -> datetime:
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return datetime.now(timezone.utc) - timedelta(hours=hours_ago)


def historical_klines(symbol: str, interval: str, limit: int, as_of: datetime) -> list[list[Any]]:
    rows = get_json(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "endTime": int(as_of.timestamp() * 1000),
            "limit": limit,
        },
    )
    as_of_ms = int(as_of.timestamp() * 1000)
    return [row for row in rows if int(row[6]) <= as_of_ms]


def build_replay_candidate(
    symbol: str,
    interval: str,
    lookback: int,
    as_of: datetime,
    *,
    context: dict[str, Any],
    min_quote_volume_usd: float,
    min_rr: float,
) -> dict[str, Any] | None:
    closed = historical_klines(symbol, interval, max(lookback, 80), as_of)
    closed_1h = historical_klines(symbol, "1h", 80, as_of)
    closed_4h = historical_klines(symbol, "4h", 80, as_of)
    if len(closed) < 50 or len(closed_1h) < 50 or len(closed_4h) < 50:
        return None

    closes = [float(row[4]) for row in closed]
    closes_1h = [float(row[4]) for row in closed_1h]
    closes_4h = [float(row[4]) for row in closed_4h]
    current = closes[-1]
    volatility = atr(closed)
    if volatility <= 0:
        return None

    quote_volume = sum(float(row[7]) for row in closed[-96:])
    if quote_volume < min_quote_volume_usd:
        return None

    fast = sma(closes, 12)
    slow = sma(closes, 30)
    fast_1h = sma(closes_1h, 20)
    slow_1h = sma(closes_1h, 50)
    fast_4h = sma(closes_4h, 20)
    slow_4h = sma(closes_4h, 50)
    rsi_15m = rsi(closes)
    rsi_1h = rsi(closes_1h)
    rsi_4h = rsi(closes_4h)

    highs_20 = [float(row[2]) for row in closed[-20:]]
    lows_20 = [float(row[3]) for row in closed[-20:]]
    recent_high = max(highs_20)
    recent_low = min(lows_20)
    previous_volumes = [float(row[5]) for row in closed[-21:-1]]
    volume_ratio = float(closed[-1][5]) / fmean(previous_volumes) if previous_volumes else 0.0
    range_position = (current - recent_low) / (recent_high - recent_low) if recent_high > recent_low else 0.5

    setup = _select_setup(
        current=current,
        fast=fast,
        slow=slow,
        fast_1h=fast_1h,
        slow_1h=slow_1h,
        fast_4h=fast_4h,
        slow_4h=slow_4h,
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
    if setup is None:
        return None
    if _regime_blocks_setup(setup["direction"], setup["setup_type"], context.get("regime")):
        return None

    direction = setup["direction"]
    entry = current
    stop_loss = setup["stop_loss"]
    take_profit = setup["take_profit"]
    risk_reward = rr(entry, stop_loss, take_profit)
    if risk_reward < min_rr:
        return None

    quality_score = 0.0
    quality_score += min(2.0, risk_reward / min_rr)
    quality_score += 1.0 if volume_ratio >= 1.0 else volume_ratio
    quality_score += 1.0
    quality_score += 1.0 if direction == "BUY" and 0.35 <= range_position <= 0.75 else 0.0
    quality_score += 1.0 if direction == "SELL" and 0.25 <= range_position <= 0.65 else 0.0
    if setup["execution_bias"] == "tomable ahora":
        quality_score += 0.5

    return {
        "source": "binance_market",
        "provider": "binance_public_api",
        "asset": symbol,
        "direction": direction,
        "entry": round(entry, 8),
        "current_price": round(current, 8),
        "stop_loss": round(stop_loss, 8),
        "take_profits": [round(take_profit, 8)],
        "timestamp": as_of.isoformat(),
        "evidence": (
            f"{interval} replay closed-candle {setup['setup_type']}: {setup['condition']}; "
            f"RR={risk_reward:.2f}; RSI15={rsi_15m:.1f}; RSI1h={rsi_1h:.1f}; "
            f"RSI4h={rsi_4h:.1f}; vol_ratio={volume_ratio:.2f}; "
            f"proxyEntry={entry:.8f}; quoteVolApprox={quote_volume:.0f}"
        ),
        "confidence": "high" if quality_score >= 4.0 else "medium",
        "market_valid": True,
        "quality_score": round(quality_score, 4),
        "setup_type": setup["setup_type"],
        "execution_bias": setup["execution_bias"],
        "regime": context.get("regime"),
        "source_context": context,
        "analysis": {
            "closed_candle_time": datetime.fromtimestamp(int(closed[-1][6]) / 1000, tz=timezone.utc).isoformat(),
            "signal_price": round(current, 8),
            "bid": round(current, 8),
            "ask": round(current, 8),
            "executable_entry": round(entry, 8),
            "spread": 0,
            "rsi_15m": round(rsi_15m, 2),
            "rsi_1h": round(rsi_1h, 2),
            "rsi_4h": round(rsi_4h, 2),
            "volume_ratio_15m": round(volume_ratio, 4),
            "range_position_20": round(range_position, 4),
            "quote_volume_approx": round(quote_volume, 2),
            "replay_note": "Historical Binance replay uses candle close as executable proxy; no historical bid/ask spread.",
        },
    }


def outcome_after(candidate: dict[str, Any], as_of: datetime, until: datetime) -> dict[str, Any]:
    symbol = str(candidate["source_context"]["market_symbol"])
    rows = get_json(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": "15m",
            "startTime": int(as_of.timestamp() * 1000),
            "endTime": int(until.timestamp() * 1000),
            "limit": 1000,
        },
    )
    direction = candidate["direction"]
    stop_loss = float(candidate["stop_loss"])
    take_profit = float(candidate["take_profits"][0])
    for row in rows:
        high = float(row[2])
        low = float(row[3])
        hit_tp = high >= take_profit if direction == "BUY" else low <= take_profit
        hit_sl = low <= stop_loss if direction == "BUY" else high >= stop_loss
        hit_time = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc).isoformat()
        if hit_tp and hit_sl:
            return {"result": "ambiguous_same_candle", "time": hit_time}
        if hit_tp:
            return {"result": "tp_first", "time": hit_time}
        if hit_sl:
            return {"result": "sl_first", "time": hit_time}
    return {"result": "open_no_touch", "time": None}


def replay_outcome_section(candidates: list[dict[str, Any]]) -> str:
    lines = [
        "",
        "## Replay Outcome",
        "",
        "| Asset | Direction | Entry | SL | TP | Result | Time |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for candidate in candidates:
        outcome = candidate.get("replay_outcome") or {}
        tp = (candidate.get("take_profits") or [""])[0]
        lines.append(
            "| {asset} | {direction} | {entry} | {sl} | {tp} | {result} | {time} |".format(
                asset=candidate.get("asset", ""),
                direction=candidate.get("direction", ""),
                entry=candidate.get("entry", ""),
                sl=candidate.get("stop_loss", ""),
                tp=tp,
                result=outcome.get("result", "unknown"),
                time=outcome.get("time") or "",
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and evaluate an intraday replay session.")
    parser.add_argument("--config-dir", type=Path, default=Path("config"))
    parser.add_argument("--hours-ago", type=float, default=4.0)
    parser.add_argument("--as-of")
    parser.add_argument("--top-assets", type=int, default=80)
    parser.add_argument("--max-symbols", type=int, default=60)
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--broker", default="fbs", choices=["fbs", "none"])
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--lookback", type=int, default=96)
    parser.add_argument("--min-quote-volume-usd", type=float, default=10_000_000)
    parser.add_argument("--min-rr", type=float, default=1.6)
    args = parser.parse_args()

    params = session_params(args.config_dir)
    as_of = parse_as_of(args.as_of, args.hours_ago)
    until = datetime.now(timezone.utc)
    symbols, context_by_symbol, metadata = build_universe(args.config_dir, args.top_assets, [symbol.upper() for symbol in args.symbols], args.broker)
    fear_greed = fetch_fear_greed()
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for symbol in symbols[: args.max_symbols]:
        context = dict(context_by_symbol.get(symbol, {}))
        context["regime"] = fear_greed["regime"]
        context["fear_greed"] = fear_greed
        try:
            candidate = build_replay_candidate(
                symbol,
                args.interval,
                args.lookback,
                as_of,
                context=context,
                min_quote_volume_usd=args.min_quote_volume_usd,
                min_rr=args.min_rr,
            )
        except Exception as exc:
            errors.append({"source": "binance_market", "provider": "binance_public_api", "asset": symbol, "missing": ["market_data"], "error": str(exc)})
            continue
        if not candidate:
            continue
        candidate["source_context"]["regime_alignment"] = regime_alignment(candidate["direction"], fear_greed["regime"])
        candidate["source_context"]["market_symbol"] = symbol
        candidate["source_context"]["broker"] = args.broker
        candidate["asset"] = context.get("broker_symbol", symbol)
        candidate = enrich_candidate(candidate, float(params["capital_usd"]), float(params["max_risk_usd"]), 2)
        if args.broker == "fbs":
            candidate["evidence"] = f"{candidate['evidence']}; broker=FBS; marketProxy={symbol}"
            candidate["risk_usd"] = None
            candidate["size"] = "TBD"
        candidate["replay_outcome"] = outcome_after(candidate, as_of, until)
        candidates.append(candidate)

    metadata.update(
        {
            "scanned_symbols": min(len(symbols), args.max_symbols),
            "candidate_count": len(candidates),
            "error_count": len(errors),
            "fear_greed": fear_greed,
            "sources": ["binance_public_api_replay", "coingecko_markets_current", "alternative_me_fng_current"],
            "as_of": as_of.isoformat(),
            "evaluated_until": until.isoformat(),
        }
    )

    output_dir = Path("sessions") / until.date().isoformat() / f"replay-{as_of.strftime('%H%M')}-utc"
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = output_dir / "crypto-web-candidates.json"
    metadata_path = output_dir / "crypto-web-metadata.json"
    report_path = output_dir / "session-report.md"
    candidates_path.write_text(json.dumps(candidates + errors, indent=2, sort_keys=True) + "\n")
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    report = render_report(candidates + errors, float(params["max_risk_usd"]), metadata)
    report_path.write_text(report + replay_outcome_section(candidates))
    print(json.dumps({"candidates": str(candidates_path), "metadata": str(metadata_path), "report": str(report_path), "count": len(candidates)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
