#!/usr/bin/env python3
"""Fetch Binance public market data and emit filtered crypto setup candidates."""

from __future__ import annotations

import argparse
import json
import statistics
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


BASE_URL = "https://api.binance.com"
MIN_QUOTE_VOLUME_USD = 10_000_000
MAX_SPREAD_PERCENT = 0.06
MIN_RR = 1.6


def fmean(values: list[float]) -> float:
    return statistics.fmean(values)


def sma(values: list[float], length: int) -> float:
    return fmean(values[-length:])


def atr(rows: list[list[Any]], length: int = 14) -> float:
    true_ranges = []
    for index in range(1, len(rows)):
        high = float(rows[index][2])
        low = float(rows[index][3])
        previous_close = float(rows[index - 1][4])
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return fmean(true_ranges[-length:])


def rsi(closes: list[float], length: int = 14) -> float:
    gains = []
    losses = []
    for index in range(1, len(closes)):
        change = closes[index] - closes[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = fmean(gains[-length:])
    average_loss = fmean(losses[-length:])
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))


def pct_distance(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return abs(a - b) / b * 100


def rr(entry: float, stop_loss: float, take_profit: float) -> float:
    risk = abs(entry - stop_loss)
    if risk == 0:
        return 0.0
    return abs(take_profit - entry) / risk


def get_json(path: str, params: dict[str, Any] | None = None) -> Any:
    query = urllib.parse.urlencode(params or {})
    url = f"{BASE_URL}{path}"
    if query:
        url = f"{url}?{query}"
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def build_candidate(
    symbol: str,
    interval: str,
    lookback: int,
    *,
    context: dict[str, Any] | None = None,
    min_quote_volume_usd: float = MIN_QUOTE_VOLUME_USD,
    max_spread_percent: float = MAX_SPREAD_PERCENT,
    min_rr: float = MIN_RR,
) -> dict[str, Any] | None:
    klines = get_json("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": max(lookback, 80)})
    klines_1h = get_json("/api/v3/klines", {"symbol": symbol, "interval": "1h", "limit": 80})
    klines_4h = get_json("/api/v3/klines", {"symbol": symbol, "interval": "4h", "limit": 80})
    ticker = get_json("/api/v3/ticker/bookTicker", {"symbol": symbol})
    ticker_24h = get_json("/api/v3/ticker/24hr", {"symbol": symbol})

    # Binance includes the currently forming candle. Use only closed candles for signals.
    closed = klines[:-1]
    closed_1h = klines_1h[:-1]
    closed_4h = klines_4h[:-1]
    closes = [float(row[4]) for row in closed]
    closes_1h = [float(row[4]) for row in closed_1h]
    closes_4h = [float(row[4]) for row in closed_4h]
    if len(closes) < 50 or len(closes_1h) < 50 or len(closes_4h) < 50:
        return None

    current = closes[-1]
    bid = float(ticker["bidPrice"])
    ask = float(ticker["askPrice"])
    spread = ask - bid
    spread_percent = spread / current * 100
    quote_volume = float(ticker_24h["quoteVolume"])
    if quote_volume < min_quote_volume_usd or spread_percent > max_spread_percent:
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

    direction = setup["direction"]
    stop_loss = setup["stop_loss"]
    take_profit = setup["take_profit"]
    risk_reward = rr(current, stop_loss, take_profit)
    if risk_reward < min_rr:
        return None

    quality_score = 0.0
    quality_score += min(2.0, risk_reward / min_rr)
    quality_score += 1.0 if volume_ratio >= 1.0 else volume_ratio
    quality_score += 1.0 if spread_percent <= 0.02 else 0.5
    quality_score += 1.0 if direction == "BUY" and 0.35 <= range_position <= 0.75 else 0.0
    quality_score += 1.0 if direction == "SELL" and 0.25 <= range_position <= 0.65 else 0.0
    if setup["execution_bias"] == "tomable ahora":
        quality_score += 0.5
    if context and context.get("regime_alignment") == "aligned":
        quality_score += 0.25
    confidence = "high" if quality_score >= 4.0 else "medium"

    context_evidence = _context_evidence(context)
    return {
        "source": "binance_market",
        "provider": "binance_public_api",
        "asset": symbol,
        "direction": direction,
        "entry": round(current, 8),
        "current_price": round(current, 8),
        "stop_loss": round(stop_loss, 8),
        "take_profits": [round(take_profit, 8)],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "evidence": (
            f"{interval} closed-candle {setup['setup_type']}: {setup['condition']}; "
            f"RR={risk_reward:.2f}; RSI15={rsi_15m:.1f}; RSI1h={rsi_1h:.1f}; "
            f"RSI4h={rsi_4h:.1f}; vol_ratio={volume_ratio:.2f}; "
            f"spread={spread:.8f} ({spread_percent:.4f}%); quoteVol24h={quote_volume:.0f}"
            f"{context_evidence}"
        ),
        "confidence": confidence,
        "market_valid": True,
        "quality_score": round(quality_score, 4),
        "setup_type": setup["setup_type"],
        "execution_bias": setup["execution_bias"],
        "regime": (context or {}).get("regime"),
        "source_context": context or {},
        "liquidity_rank": (context or {}).get("liquidity_rank"),
        "analysis": {
            "closed_candle_time": datetime.fromtimestamp(int(closed[-1][6]) / 1000, tz=timezone.utc).isoformat(),
            "rsi_15m": round(rsi_15m, 2),
            "rsi_1h": round(rsi_1h, 2),
            "rsi_4h": round(rsi_4h, 2),
            "volume_ratio_15m": round(volume_ratio, 4),
            "spread_percent": round(spread_percent, 5),
            "range_position_20": round(range_position, 4),
            "quote_volume_24h": round(quote_volume, 2),
        },
    }


def _select_setup(
    *,
    current: float,
    fast: float,
    slow: float,
    fast_1h: float,
    slow_1h: float,
    fast_4h: float,
    slow_4h: float,
    rsi_15m: float,
    rsi_1h: float,
    rsi_4h: float,
    volume_ratio: float,
    range_position: float,
    recent_high: float,
    recent_low: float,
    volatility: float,
    min_rr: float,
) -> dict[str, Any] | None:
    uptrend = fast > slow * 1.001 and fast_1h > slow_1h and fast_4h >= slow_4h
    downtrend = fast < slow * 0.999 and fast_1h < slow_1h and fast_4h <= slow_4h
    bullish_rsi = 45 <= rsi_15m <= 68 and rsi_1h < 78 and rsi_4h < 76
    bearish_rsi = 32 <= rsi_15m <= 58 and rsi_1h > 25 and rsi_4h > 28
    enough_volume = volume_ratio >= 0.45
    strong_volume = volume_ratio >= 0.85

    if uptrend and bullish_rsi and enough_volume and range_position <= 0.85:
        stop_loss = min(recent_low - (0.25 * volatility), current - (1.2 * volatility))
        return _setup("trend_continuation", "tomable ahora", "BUY", current, stop_loss, min_rr, "15m/1h/4h uptrend with controlled RSI and confirmed volume")

    if downtrend and bearish_rsi and enough_volume and range_position >= 0.15:
        stop_loss = max(recent_high + (0.25 * volatility), current + (1.2 * volatility))
        return _setup("trend_continuation", "tomable ahora", "SELL", current, stop_loss, min_rr, "15m/1h/4h downtrend with controlled RSI and confirmed volume")

    if uptrend and 38 <= rsi_15m <= 55 and rsi_1h < 72 and 0.15 <= range_position <= 0.45 and enough_volume:
        stop_loss = min(recent_low - (0.2 * volatility), current - volatility)
        return _setup("pullback", "solo con pullback", "BUY", current, stop_loss, min_rr, "uptrend pullback near recent range support")

    if downtrend and 45 <= rsi_15m <= 62 and rsi_1h > 30 and 0.55 <= range_position <= 0.9 and enough_volume:
        stop_loss = max(recent_high + (0.2 * volatility), current + volatility)
        return _setup("pullback", "solo con pullback", "SELL", current, stop_loss, min_rr, "downtrend pullback near recent range resistance")

    if fast_1h > slow_1h and fast_4h >= slow_4h and current >= recent_high - (0.2 * volatility) and rsi_15m <= 72 and strong_volume:
        stop_loss = current - max(1.1 * volatility, current - recent_low)
        return _setup("breakout", "solo con ruptura", "BUY", current, stop_loss, min_rr, "bullish breakout attempt with higher-timeframe support")

    if fast_1h < slow_1h and fast_4h <= slow_4h and current <= recent_low + (0.2 * volatility) and rsi_15m >= 28 and strong_volume:
        stop_loss = current + max(1.1 * volatility, recent_high - current)
        return _setup("breakout", "solo con ruptura", "SELL", current, stop_loss, min_rr, "bearish breakdown attempt with higher-timeframe pressure")

    if fast_4h >= slow_4h and range_position <= 0.2 and 28 <= rsi_15m <= 42 and rsi_1h >= 30 and strong_volume:
        stop_loss = recent_low - (0.35 * volatility)
        return _setup("controlled_reversal", "solo con ruptura", "BUY", current, stop_loss, min_rr, "controlled rebound from lower range with 4h support")

    if fast_4h <= slow_4h and range_position >= 0.8 and 58 <= rsi_15m <= 72 and rsi_1h <= 70 and strong_volume:
        stop_loss = recent_high + (0.35 * volatility)
        return _setup("controlled_reversal", "solo con ruptura", "SELL", current, stop_loss, min_rr, "controlled rejection from upper range with 4h pressure")

    return None


def _setup(setup_type: str, execution_bias: str, direction: str, current: float, stop_loss: float, min_rr: float, condition: str) -> dict[str, Any]:
    if direction == "BUY":
        take_profit = current + max((current - stop_loss) * min_rr, 2.0 * abs(current - stop_loss) / 1.2)
    else:
        take_profit = current - max((stop_loss - current) * min_rr, 2.0 * abs(stop_loss - current) / 1.2)
    return {
        "setup_type": setup_type,
        "execution_bias": execution_bias,
        "direction": direction,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "condition": condition,
    }


def _context_evidence(context: dict[str, Any] | None) -> str:
    if not context:
        return ""
    parts = []
    if context.get("coingecko_rank"):
        parts.append(f"cgRank={context['coingecko_rank']}")
    if context.get("price_change_24h") is not None:
        parts.append(f"cg24h={float(context['price_change_24h']):.2f}%")
    if context.get("regime"):
        parts.append(f"regime={context['regime']}")
    return "; " + "; ".join(parts) if parts else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--lookback", type=int, default=96)
    parser.add_argument("--min-quote-volume-usd", type=float, default=MIN_QUOTE_VOLUME_USD)
    parser.add_argument("--max-spread-percent", type=float, default=MAX_SPREAD_PERCENT)
    parser.add_argument("--min-rr", type=float, default=MIN_RR)
    args = parser.parse_args()

    candidates = []
    for symbol in args.symbols:
        try:
            candidate = build_candidate(
                symbol.upper(),
                args.interval,
                args.lookback,
                min_quote_volume_usd=args.min_quote_volume_usd,
                max_spread_percent=args.max_spread_percent,
                min_rr=args.min_rr,
            )
            if candidate:
                candidates.append(candidate)
        except urllib.error.URLError as exc:
            candidates.append({"source": "binance_market", "provider": "binance_public_api", "asset": symbol.upper(), "missing": ["market_data"], "error": str(exc)})
    print(json.dumps(candidates, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
