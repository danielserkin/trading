#!/usr/bin/env python3
"""Walk-forward comparison of intraday FX signal families.

This research tool is intentionally separate from production. It uses only data
available at each signal close, enters on the next 15-minute bar, applies a
spread/slippage estimate, limits the portfolio to three trades per UTC day, and
reserves the final chronological block for out-of-sample validation.
"""

from __future__ import annotations

import argparse
import json
import math
import random
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
DEFAULT_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURJPY", "GBPJPY", "EURGBP", "AUDJPY", "EURAUD", "GBPAUD", "GBPCAD", "GBPCHF",
]
SCHEDULES = {
    "core": frozenset(range(6, 17)),
    "overlap": frozenset((7, 8, 9, 12, 13, 14, 15)),
}


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class StrategyConfig:
    family: str
    schedule: str
    rr: float
    stop_atr: float
    lookback: int = 20
    threshold: float = 0.0
    trend_filter: bool = True
    min_strength: float = 0.0
    management: str = "fixed"

    @property
    def key(self) -> str:
        trend = "trend" if self.trend_filter else "raw"
        return (
            f"{self.family}|{self.schedule}|rr={self.rr:g}|atr={self.stop_atr:g}|"
            f"lb={self.lookback}|th={self.threshold:g}|minq={self.min_strength:g}|{trend}|{self.management}"
        )


class Indicators:
    def __init__(self, bars: list[Bar]) -> None:
        self.bars = bars
        self.close_prefix = [0.0]
        self.square_prefix = [0.0]
        self.tr_prefix = [0.0]
        self.gain_prefix = [0.0]
        self.loss_prefix = [0.0]
        previous = bars[0].close
        for bar in bars:
            self.close_prefix.append(self.close_prefix[-1] + bar.close)
            self.square_prefix.append(self.square_prefix[-1] + bar.close * bar.close)
            true_range = max(bar.high - bar.low, abs(bar.high - previous), abs(bar.low - previous))
            change = bar.close - previous
            self.tr_prefix.append(self.tr_prefix[-1] + true_range)
            self.gain_prefix.append(self.gain_prefix[-1] + max(change, 0.0))
            self.loss_prefix.append(self.loss_prefix[-1] + max(-change, 0.0))
            previous = bar.close

    @staticmethod
    def _window(prefix: list[float], index: int, length: int) -> float:
        start = index + 1 - length
        if start < 0:
            return math.nan
        return prefix[index + 1] - prefix[start]

    def sma(self, index: int, length: int) -> float:
        total = self._window(self.close_prefix, index, length)
        return total / length if math.isfinite(total) else math.nan

    def std(self, index: int, length: int) -> float:
        total = self._window(self.close_prefix, index, length)
        square = self._window(self.square_prefix, index, length)
        if not math.isfinite(total) or not math.isfinite(square):
            return math.nan
        variance = max(0.0, square / length - (total / length) ** 2)
        return math.sqrt(variance)

    def atr(self, index: int, length: int = 14) -> float:
        total = self._window(self.tr_prefix, index, length)
        return total / length if math.isfinite(total) else math.nan

    def rsi(self, index: int, length: int = 14) -> float:
        gains = self._window(self.gain_prefix, index, length)
        losses = self._window(self.loss_prefix, index, length)
        if not math.isfinite(gains) or not math.isfinite(losses):
            return math.nan
        if losses == 0:
            return 100.0
        ratio = gains / losses
        return 100.0 - 100.0 / (1.0 + ratio)


def yahoo_symbol(symbol: str) -> str:
    return f"{symbol}=X"


def fetch_bars(symbol: str, cache_dir: Path, range_value: str) -> list[Bar]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{symbol}-{range_value}-15m.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text())
    else:
        encoded = urllib.parse.quote(yahoo_symbol(symbol), safe="")
        query = urllib.parse.urlencode({"range": range_value, "interval": "15m", "includePrePost": "false"})
        request = urllib.request.Request(
            f"{YAHOO_URL}/{encoded}?{query}",
            headers={"User-Agent": "Mozilla/5.0 forex-walk-forward-research/1.0"},
        )
        error: Exception | None = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                cache_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
                break
            except Exception as exc:  # pragma: no cover - network behavior
                error = exc
                time.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError(f"{symbol}: Yahoo download failed: {error}")

    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(f"{symbol}: {chart['error']}")
    result = (chart.get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"{symbol}: empty Yahoo result")
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    bars: list[Bar] = []
    for index, timestamp in enumerate(timestamps):
        values = [quote.get(name, [None] * len(timestamps))[index] for name in ("open", "high", "low", "close")]
        if any(value is None for value in values):
            continue
        bars.append(
            Bar(
                timestamp=datetime.fromtimestamp(int(timestamp), tz=timezone.utc),
                open=float(values[0]), high=float(values[1]), low=float(values[2]), close=float(values[3]),
            )
        )
    bars.sort(key=lambda item: item.timestamp)
    return bars


def load_dukascopy_bars(path: Path) -> list[Bar]:
    payload = json.loads(path.read_text())
    bars = []
    for item in payload:
        timestamp = item.get("timestamp")
        if timestamp is None:
            continue
        bars.append(Bar(
            timestamp=datetime.fromtimestamp(float(timestamp) / 1000, tz=timezone.utc),
            open=float(item["open"]), high=float(item["high"]),
            low=float(item["low"]), close=float(item["close"]),
        ))
    return sorted(bars, key=lambda item: item.timestamp)


def direction_for(config: StrategyConfig, ind: Indicators, index: int) -> tuple[str, float] | None:
    bars = ind.bars
    if index < 800:
        return None
    bar = bars[index]
    previous = bars[index - 1]
    close = bar.close
    atr = ind.atr(index)
    rsi = ind.rsi(index)
    if not all(math.isfinite(value) and value > 0 for value in (close, atr)) or not math.isfinite(rsi):
        return None

    fast_15, slow_15 = ind.sma(index, 8), ind.sma(index, 20)
    fast_mid, slow_mid = ind.sma(index, 32), ind.sma(index, 128)
    fast_long, slow_long = ind.sma(index, 160), ind.sma(index, 400)
    long_trend = fast_mid > slow_mid and fast_long > slow_long
    short_trend = fast_mid < slow_mid and fast_long < slow_long

    if config.family == "strict_mtf":
        long_signal = long_trend and fast_15 > slow_15 and previous.close <= ind.sma(index - 1, 8) and close > fast_15 and rsi < 68
        short_signal = short_trend and fast_15 < slow_15 and previous.close >= ind.sma(index - 1, 8) and close < fast_15 and rsi > 32
        strength = abs(fast_15 - slow_15) / atr + abs(fast_mid - slow_mid) / atr / 4
    elif config.family == "trend_pullback":
        mean = ind.sma(index, config.lookback)
        prior_mean = ind.sma(index - 1, config.lookback)
        long_signal = long_trend and previous.close <= prior_mean and close > mean and 42 <= rsi <= 68
        short_signal = short_trend and previous.close >= prior_mean and close < mean and 32 <= rsi <= 58
        strength = abs(close - mean) / atr + abs(fast_mid - slow_mid) / atr / 4
    elif config.family == "breakout":
        previous_rows = bars[index - config.lookback:index]
        upper = max(item.high for item in previous_rows)
        lower = min(item.low for item in previous_rows)
        long_signal = close > upper and rsi < 76 and (not config.trend_filter or long_trend)
        short_signal = close < lower and rsi > 24 and (not config.trend_filter or short_trend)
        strength = max((close - upper) / atr, (lower - close) / atr, 0.0) + abs(fast_mid - slow_mid) / atr / 5
    elif config.family == "momentum":
        move = (close - bars[index - config.lookback].close) / atr
        long_signal = move >= config.threshold and rsi < 74 and (not config.trend_filter or long_trend)
        short_signal = move <= -config.threshold and rsi > 26 and (not config.trend_filter or short_trend)
        strength = abs(move)
    elif config.family == "mean_reversion":
        mean = ind.sma(index, config.lookback)
        deviation = ind.std(index, config.lookback)
        if not math.isfinite(deviation) or deviation == 0:
            return None
        zscore = (close - mean) / deviation
        range_regime = abs(fast_mid - slow_mid) / atr <= 2.5
        long_signal = range_regime and zscore <= -config.threshold and rsi <= 38
        short_signal = range_regime and zscore >= config.threshold and rsi >= 62
        strength = abs(zscore)
    elif config.family == "session_breakout":
        if bar.timestamp.hour not in (7, 8):
            return None
        same_day = [item for item in bars[max(0, index - 40):index] if item.timestamp.date() == bar.timestamp.date() and item.timestamp.hour < 7]
        if len(same_day) < 20:
            return None
        upper = max(item.high for item in same_day)
        lower = min(item.low for item in same_day)
        long_signal = close > upper + config.threshold * atr
        short_signal = close < lower - config.threshold * atr
        strength = max((close - upper) / atr, (lower - close) / atr, 0.0)
    elif config.family == "pending_breakout":
        previous_rows = bars[index - config.lookback:index]
        upper = max(item.high for item in previous_rows)
        lower = min(item.low for item in previous_rows)
        distance_up = (upper - close) / atr
        distance_down = (close - lower) / atr
        long_signal = long_trend and -0.05 <= distance_up <= config.threshold and 45 <= rsi <= 70
        short_signal = short_trend and -0.05 <= distance_down <= config.threshold and 30 <= rsi <= 55
        strength = max(config.threshold - min(distance_up, distance_down), 0.0) + abs(fast_mid - slow_mid) / atr / 5
    elif config.family == "pullback_limit":
        mean = ind.sma(index, config.lookback)
        distance = (close - mean) / atr
        long_signal = long_trend and config.threshold <= distance <= 1.25 and 45 <= rsi <= 68
        short_signal = short_trend and -1.25 <= distance <= -config.threshold and 32 <= rsi <= 55
        strength = abs(fast_mid - slow_mid) / atr / 5 + max(0.0, 1.25 - abs(distance))
    elif config.family == "session_pending":
        if bar.timestamp.hour != 7:
            return None
        same_day = [item for item in bars[max(0, index - 40):index] if item.timestamp.date() == bar.timestamp.date() and item.timestamp.hour < 7]
        if len(same_day) < 20:
            return None
        long_signal = long_trend and rsi < 70
        short_signal = short_trend and rsi > 30
        strength = abs(fast_mid - slow_mid) / atr / 4
    else:
        raise ValueError(f"Unknown family: {config.family}")

    if long_signal == short_signal or strength < config.min_strength:
        return None
    return ("BUY" if long_signal else "SELL", float(strength))


def pip_size(symbol: str) -> float:
    return 0.01 if symbol.endswith("JPY") else 0.0001


def spread_pips(symbol: str) -> float:
    if symbol in {"EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCHF", "USDCAD", "NZDUSD"}:
        return 1.2
    return 1.8


def evaluate_signal(
    symbol: str,
    ind: Indicators,
    signal_index: int,
    direction: str,
    config: StrategyConfig,
    horizon_hours: int,
    cost_scale: float,
) -> dict[str, Any] | None:
    bars = ind.bars
    if signal_index + 1 >= len(bars):
        return None
    risk = ind.atr(signal_index) * config.stop_atr
    if not math.isfinite(risk) or risk <= 0:
        return None
    entry_index = signal_index + 1
    entry_bar = bars[entry_index]
    entry = entry_bar.open
    order_type = "MARKET"
    pending_families = {"pending_breakout", "pullback_limit", "session_pending"}
    if config.family in pending_families:
        signal_bar = bars[signal_index]
        if config.family == "pullback_limit":
            requested_entry = ind.sma(signal_index, config.lookback)
            order_type = f"{direction} LIMIT"
            valid_bars = 8
        else:
            if config.family == "session_pending":
                same_day = [
                    item for item in bars[max(0, signal_index - 40):signal_index]
                    if item.timestamp.date() == signal_bar.timestamp.date() and item.timestamp.hour < 7
                ]
                prior_high = max(item.high for item in same_day)
                prior_low = min(item.low for item in same_day)
                valid_bars = 12
            else:
                prior = bars[signal_index - config.lookback:signal_index]
                prior_high = max(item.high for item in prior)
                prior_low = min(item.low for item in prior)
                valid_bars = 8
            requested_entry = prior_high + 0.05 * risk if direction == "BUY" else prior_low - 0.05 * risk
            order_type = f"{direction} STOP"
        fill_index = None
        for possible in range(entry_index, min(len(bars), entry_index + valid_bars)):
            future = bars[possible]
            filled = future.low <= requested_entry if order_type.endswith("LIMIT") and direction == "BUY" else (
                future.high >= requested_entry if order_type.endswith("LIMIT") and direction == "SELL" else (
                    future.high >= requested_entry if direction == "BUY" else future.low <= requested_entry
                )
            )
            if filled:
                fill_index = possible
                break
        if fill_index is None:
            expiry_index = min(len(bars) - 1, entry_index + valid_bars - 1)
            return {
                "symbol": symbol, "direction": direction,
                "signal_at": bars[signal_index].timestamp.isoformat(),
                "entry_at": None, "exit_at": bars[expiry_index].timestamp.isoformat(),
                "entry": requested_entry, "stop": None, "target": None,
                "order_type": order_type, "result": "not_filled",
                "gross_r": None, "cost_r": None, "net_r": None,
            }
        entry_index = fill_index
        entry_bar = bars[entry_index]
        entry = requested_entry
    stop = entry - risk if direction == "BUY" else entry + risk
    target = entry + config.rr * risk if direction == "BUY" else entry - config.rr * risk
    deadline = entry_bar.timestamp + timedelta(hours=horizon_hours)
    last_bar: Bar | None = None
    exit_time: datetime | None = None
    raw_r: float | None = None
    result = "timeout"
    partial_active = False
    for future in bars[entry_index:]:
        if future.timestamp > deadline:
            break
        last_bar = future
        hit_tp = future.high >= target if direction == "BUY" else future.low <= target
        hit_sl = future.low <= stop if direction == "BUY" else future.high >= stop
        if hit_tp and hit_sl:
            raw_r = 0.4 if config.management == "partial_08" and partial_active else -1.0
            result = "protected_exit" if partial_active else "ambiguous_as_sl"
            exit_time = future.timestamp
            break
        if hit_sl:
            raw_r = 0.4 if config.management == "partial_08" and partial_active else -1.0
            result = "protected_exit" if partial_active else "sl"
            exit_time = future.timestamp
            break
        if hit_tp:
            raw_r = 0.4 + 0.5 * config.rr if config.management == "partial_08" else config.rr
            result, exit_time = "tp", future.timestamp
            break
        if config.management == "partial_08" and not partial_active:
            partial_level = entry + 0.8 * risk if direction == "BUY" else entry - 0.8 * risk
            if (future.high >= partial_level if direction == "BUY" else future.low <= partial_level):
                partial_active = True
                stop = entry
    if last_bar is None:
        return None
    if raw_r is None:
        raw_r = (last_bar.close - entry) / risk if direction == "BUY" else (entry - last_bar.close) / risk
        raw_r = max(-1.0, min(config.rr, raw_r))
        if config.management == "partial_08" and partial_active:
            raw_r = 0.4 + 0.5 * raw_r
        exit_time = last_bar.timestamp
    cost = (spread_pips(symbol) + 0.2) * pip_size(symbol) * cost_scale / risk
    net_r = raw_r - cost
    return {
        "symbol": symbol,
        "direction": direction,
        "signal_at": bars[signal_index].timestamp.isoformat(),
        "entry_at": entry_bar.timestamp.isoformat(),
        "exit_at": exit_time.isoformat() if exit_time else None,
        "entry": entry,
        "stop": stop,
        "target": target,
        "order_type": order_type,
        "result": result,
        "gross_r": round(raw_r, 5),
        "cost_r": round(cost, 5),
        "net_r": round(net_r, 5),
    }


def simulate(
    data: dict[str, Indicators],
    config: StrategyConfig,
    allowed_dates: set[date],
    horizon_hours: int,
    max_daily_trades: int,
    cost_scale: float = 1.0,
) -> list[dict[str, Any]]:
    opportunities: list[tuple[datetime, float, str, int, str]] = []
    hours = SCHEDULES[config.schedule]
    for symbol, ind in data.items():
        for index, bar in enumerate(ind.bars):
            signal_close = bar.timestamp + timedelta(minutes=15)
            if signal_close.date() not in allowed_dates or signal_close.minute != 0 or signal_close.hour not in hours:
                continue
            signal = direction_for(config, ind, index)
            if signal:
                direction, strength = signal
                opportunities.append((signal_close, strength, symbol, index, direction))
    opportunities.sort(key=lambda item: (item[0], -item[1], item[2]))

    selected: list[dict[str, Any]] = []
    daily_count: dict[date, int] = defaultdict(int)
    active_until: dict[str, datetime] = {}
    for signal_time, strength, symbol, index, direction in opportunities:
        trade_day = signal_time.date()
        if daily_count[trade_day] >= max_daily_trades or active_until.get(symbol, signal_time) > signal_time:
            continue
        trade = evaluate_signal(symbol, data[symbol], index, direction, config, horizon_hours, cost_scale)
        if not trade:
            continue
        trade["strength"] = round(strength, 5)
        trade["config"] = config.key
        selected.append(trade)
        daily_count[trade_day] += 1
        active_until[symbol] = datetime.fromisoformat(trade["exit_at"])
    return selected


def max_drawdown(values: list[float]) -> float:
    equity = peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return abs(drawdown)


def metrics(trades: list[dict[str, Any]], trading_days: int) -> dict[str, Any]:
    values = [float(item["net_r"]) for item in trades if item.get("net_r") is not None]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value <= 0]
    covered = {str(item["signal_at"])[:10] for item in trades}
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "signals": len(trades),
        "trades": len(values),
        "not_filled": sum(item.get("result") == "not_filled" for item in trades),
        "wins": len(wins),
        "win_rate": round(100 * len(wins) / len(values), 2) if values else 0.0,
        "total_r": round(sum(values), 4),
        "avg_r": round(statistics.fmean(values), 4) if values else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else (999.0 if gross_profit else 0.0),
        "max_drawdown_r": round(max_drawdown(values), 4),
        "days_with_signal": len(covered),
        "coverage_percent": round(100 * len(covered) / trading_days, 2) if trading_days else 0.0,
    }


def configs() -> list[StrategyConfig]:
    result: list[StrategyConfig] = []
    for schedule in SCHEDULES:
        for rr in (1.3, 1.6):
            for stop in (1.0, 1.3):
                result.append(StrategyConfig("strict_mtf", schedule, rr, stop))
                for lookback in (12, 20):
                    result.append(StrategyConfig("trend_pullback", schedule, rr, stop, lookback=lookback))
                for lookback in (12, 20, 32):
                    for trend_filter in (False, True):
                        result.append(StrategyConfig("breakout", schedule, rr, stop, lookback=lookback, trend_filter=trend_filter))
                for lookback in (4, 8, 16):
                    for threshold in (0.7, 1.1):
                        result.append(StrategyConfig("momentum", schedule, rr, stop, lookback=lookback, threshold=threshold))
                for lookback in (20, 32):
                    for threshold in (1.5, 2.0):
                        result.append(StrategyConfig("mean_reversion", schedule, rr, stop, lookback=lookback, threshold=threshold, trend_filter=False))
                for lookback in (12, 20, 32):
                    for threshold in (0.6, 1.0):
                        result.append(StrategyConfig("pending_breakout", schedule, rr, stop, lookback=lookback, threshold=threshold))
                for lookback in (12, 20):
                    for threshold in (0.0, 0.25):
                        result.append(StrategyConfig("pullback_limit", schedule, rr, stop, lookback=lookback, threshold=threshold))
    for rr in (1.3, 1.6):
        for stop in (1.0, 1.3):
            for threshold in (0.0, 0.1):
                result.append(StrategyConfig("session_breakout", "core", rr, stop, threshold=threshold))
                result.append(StrategyConfig("session_pending", "core", rr, stop, threshold=threshold))
    for schedule in SCHEDULES:
        for rr in (1.0, 1.2, 1.4, 1.6):
            for stop in (1.0, 1.3, 1.6, 2.0):
                management_options = ("fixed", "partial_08") if rr >= 1.4 else ("fixed",)
                for management in management_options:
                    for lookback in (12, 20):
                        for threshold in (0.0, 0.25):
                            for min_strength in (0.0, 0.75):
                                result.append(StrategyConfig(
                                    "pullback_limit", schedule, rr, stop, lookback=lookback,
                                    threshold=threshold, min_strength=min_strength, management=management,
                                ))
        for rr in (1.2, 1.6):
            for stop in (1.3, 1.6):
                for lookback in (12, 20, 32):
                    for threshold in (0.6, 1.0):
                        for min_strength in (0.0, 0.5):
                            result.append(StrategyConfig(
                                "pending_breakout", schedule, rr, stop, lookback=lookback,
                                threshold=threshold, min_strength=min_strength,
                            ))
    return list({item.key: item for item in result}.values())


def trading_dates(data: dict[str, Indicators]) -> list[date]:
    dates = {bar.timestamp.date() for ind in data.values() for bar in ind.bars if bar.timestamp.weekday() < 5}
    return sorted(dates)


def candidate_score(full: dict[str, Any], fold_a: dict[str, Any], fold_b: dict[str, Any]) -> float:
    if full["trades"] < 20:
        return -1000 + full["trades"]
    stability = min(fold_a["avg_r"], fold_b["avg_r"])
    return stability * 6 + full["avg_r"] * 3 + full["coverage_percent"] / 100 - full["max_drawdown_r"] * 0.03


def bootstrap_mean_interval(trades: list[dict[str, Any]], iterations: int = 3000) -> list[float] | None:
    values = [float(item["net_r"]) for item in trades if item.get("net_r") is not None]
    if len(values) < 2:
        return None
    rng = random.Random(20260909)
    samples = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(iterations))
    return [round(samples[int(iterations * 0.025)], 4), round(samples[int(iterations * 0.975)], 4)]


def render_report(payload: dict[str, Any]) -> str:
    meta = payload["metadata"]
    lines = [
        "# Forex strategy walk-forward research",
        "",
        "## Design",
        "",
        f"- Data: {meta['provider']}, {meta['start']} through {meta['end']}.",
        f"- Symbols: {', '.join(meta['symbols'])}.",
        f"- Chronological split: train through {meta['train_end']}; untouched validation from {meta['test_start']}.",
        f"- Tested configurations: {meta['configurations_tested']} across {meta['families_tested']} signal families.",
        f"- Execution: next-bar open, {meta['horizon_hours']}h maximum hold, maximum {meta['max_daily_trades']} trades/day.",
        "- Costs: estimated spread plus 0.2 pip slippage; same-candle TP/SL ambiguity is counted as SL.",
        "",
        "## Best training configuration per family",
        "",
        "| Family | Configuration | Signals/Fills | Coverage | Avg R | Total R | PF | Max DD | Fold A/B Avg R |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in payload["best_by_family"]:
        item = row["train"]
        lines.append(
            f"| {row['family']} | `{row['config']}` | {item['signals']}/{item['trades']} | {item['coverage_percent']}% | {item['avg_r']} | "
            f"{item['total_r']} | {item['profit_factor']} | {item['max_drawdown_r']}R | {row['fold_a']['avg_r']} / {row['fold_b']['avg_r']} |"
        )
    source_limits = (
        [
            "- Dukascopy bid candles are historical quotes; ask-side execution and the actual FBS spread are estimated.",
            "- Only symbols with complete downloads are included; Dukascopy rate limits prevented a broader independent universe.",
        ]
        if str(meta.get("provider", "")).startswith("Dukascopy")
        else [
            "- Yahoo candles are indicative midpoint proxies, not executable FBS bid/ask quotes.",
            "- The sample is short because the public source limits 15-minute history to about 60 days.",
        ]
    )
    lines.extend([
        "",
        "## Untouched validation of the five training winners",
        "",
        "| Rank | Configuration | Signals/Fills | Coverage | Win rate | Avg R | Total R | PF | Max DD |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in payload["validation_top_five"]:
        item = row["validation"]
        lines.append(
            f"| {row['train_rank']} | `{row['config']}` | {item['signals']}/{item['trades']} | {item['coverage_percent']}% | {item['win_rate']}% | "
            f"{item['avg_r']} | {item['total_r']} | {item['profit_factor']} | {item['max_drawdown_r']}R |"
        )
    champion = payload["champion"]
    lines.extend([
        "",
        "## Predeclared production gate",
        "",
        f"- Selected only from training: `{champion['config']}`.",
        f"- Validation 95% bootstrap interval for mean R/trade: {champion['validation_mean_r_ci95']}.",
        f"- Cost stress (1.5x / 2.0x) average R: {champion['stress_1_5x']['avg_r']} / {champion['stress_2x']['avg_r']}.",
        f"- Gate result: **{payload['production_gate']['status']}**.",
        f"- Reason: {payload['production_gate']['reason']}",
        "",
        "## Daily validation",
        "",
        "| Date | Trades | Net R |",
        "| --- | ---: | ---: |",
    ])
    for row in champion["daily_validation"]:
        lines.append(f"| {row['date']} | {row['trades']} | {row['net_r']} |")
    lines.extend([
        "",
        "## Limits",
        "",
        *source_limits,
        "- Swap, news-calendar filtering, variable spreads, rejected orders, and partial fills are not modeled.",
        "- A positive result is a hypothesis for demo forward testing, not evidence of guaranteed future profit.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    parser.add_argument("--range", default="60d")
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/trading-forex-cache"))
    parser.add_argument("--dukascopy-data-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("research/results/forex-walk-forward"))
    parser.add_argument("--horizon-hours", type=int, default=8)
    parser.add_argument("--max-daily-trades", type=int, default=3)
    parser.add_argument("--train-fraction", type=float, default=0.70)
    args = parser.parse_args()

    raw: dict[str, list[Bar]] = {}
    errors: dict[str, str] = {}
    if args.dukascopy_data_dir:
        for path in sorted(args.dukascopy_data_dir.glob("*-m15-bid.json")):
            symbol = path.name.split("-", 1)[0]
            try:
                bars = load_dukascopy_bars(path)
                if len(bars) < 1200:
                    raise RuntimeError(f"only {len(bars)} usable bars")
                raw[symbol] = bars
            except Exception as exc:
                errors[symbol] = str(exc)
    else:
        for symbol in args.symbols:
            try:
                bars = fetch_bars(symbol.upper(), args.cache_dir, args.range)
                if len(bars) < 1200:
                    raise RuntimeError(f"only {len(bars)} usable bars")
                raw[symbol.upper()] = bars
            except Exception as exc:
                errors[symbol.upper()] = str(exc)
    if len(raw) < 4:
        raise RuntimeError(f"Insufficient data: {errors}")
    data = {symbol: Indicators(bars) for symbol, bars in raw.items()}
    dates = trading_dates(data)
    split_index = max(2, min(len(dates) - 2, int(len(dates) * args.train_fraction)))
    train_dates, test_dates = dates[:split_index], dates[split_index:]
    fold_index = len(train_dates) // 2
    fold_a_dates, fold_b_dates = set(train_dates[:fold_index]), set(train_dates[fold_index:])
    train_set, test_set = set(train_dates), set(test_dates)

    evaluated = []
    for config in configs():
        trades = simulate(data, config, train_set, args.horizon_hours, args.max_daily_trades)
        full = metrics(trades, len(train_dates))
        fold_a = metrics([item for item in trades if datetime.fromisoformat(item["signal_at"]).date() in fold_a_dates], len(fold_a_dates))
        fold_b = metrics([item for item in trades if datetime.fromisoformat(item["signal_at"]).date() in fold_b_dates], len(fold_b_dates))
        evaluated.append({
            "config": config,
            "train": full,
            "fold_a": fold_a,
            "fold_b": fold_b,
            "score": candidate_score(full, fold_a, fold_b),
        })
    evaluated.sort(key=lambda item: (item["score"], item["train"]["total_r"]), reverse=True)

    best_by_family = []
    for family in sorted({item["config"].family for item in evaluated}):
        row = next(item for item in evaluated if item["config"].family == family)
        best_by_family.append({
            "family": family, "config": row["config"].key, "train": row["train"],
            "fold_a": row["fold_a"], "fold_b": row["fold_b"], "score": round(row["score"], 5),
        })

    validation_top_five = []
    for rank, row in enumerate(evaluated[:5], start=1):
        validation_trades = simulate(data, row["config"], test_set, args.horizon_hours, args.max_daily_trades)
        validation_top_five.append({
            "train_rank": rank,
            "config": row["config"].key,
            "train": row["train"],
            "validation": metrics(validation_trades, len(test_dates)),
            "validation_trades": validation_trades,
        })

    winner = evaluated[0]
    champion_trades = validation_top_five[0]["validation_trades"]
    stress_1_5 = simulate(data, winner["config"], test_set, args.horizon_hours, args.max_daily_trades, cost_scale=1.5)
    stress_2 = simulate(data, winner["config"], test_set, args.horizon_hours, args.max_daily_trades, cost_scale=2.0)
    daily: dict[str, list[float]] = defaultdict(list)
    for trade in champion_trades:
        if trade.get("net_r") is not None:
            daily[str(trade["signal_at"])[:10]].append(float(trade["net_r"]))
    daily_validation = [
        {"date": day.isoformat(), "trades": len(daily.get(day.isoformat(), [])), "net_r": round(sum(daily.get(day.isoformat(), [])), 4)}
        for day in test_dates
    ]
    validation = validation_top_five[0]["validation"]
    stress_1_5_metrics = metrics(stress_1_5, len(test_dates))
    stress_2_metrics = metrics(stress_2, len(test_dates))
    gate_conditions = {
        "at_least_15_validation_trades": validation["trades"] >= 15,
        "at_least_50pct_days_with_signal": validation["coverage_percent"] >= 50,
        "avg_r_at_least_0_10": validation["avg_r"] >= 0.10,
        "profit_factor_at_least_1_20": validation["profit_factor"] >= 1.20,
        "positive_at_double_cost": stress_2_metrics["avg_r"] > 0,
    }
    passed = all(gate_conditions.values())
    failed = [key for key, value in gate_conditions.items() if not value]
    gate = {
        "status": "PASS — eligible for demo forward test" if passed else "FAIL — do not change production",
        "conditions": gate_conditions,
        "reason": "All robustness conditions passed." if passed else "Failed: " + ", ".join(failed),
    }

    payload = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "provider": "Dukascopy m15 bid" if args.dukascopy_data_dir else "Yahoo 15-minute midpoint proxy",
            "start": dates[0].isoformat(), "end": dates[-1].isoformat(),
            "train_end": train_dates[-1].isoformat(), "test_start": test_dates[0].isoformat(),
            "symbols": sorted(data), "download_errors": errors,
            "configurations_tested": len(evaluated),
            "families_tested": len({item["config"].family for item in evaluated}),
            "horizon_hours": args.horizon_hours, "max_daily_trades": args.max_daily_trades,
            "train_days": len(train_dates), "validation_days": len(test_dates),
        },
        "best_by_family": best_by_family,
        "training_top_five": [
            {"rank": index, "config": row["config"].key, "train": row["train"], "fold_a": row["fold_a"], "fold_b": row["fold_b"], "score": round(row["score"], 5)}
            for index, row in enumerate(evaluated[:5], start=1)
        ],
        "validation_top_five": validation_top_five,
        "champion": {
            "config": winner["config"].key,
            "train": winner["train"],
            "validation": validation,
            "validation_mean_r_ci95": bootstrap_mean_interval(champion_trades),
            "stress_1_5x": stress_1_5_metrics,
            "stress_2x": stress_2_metrics,
            "daily_validation": daily_validation,
        },
        "production_gate": gate,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "report.md").write_text(render_report(payload))
    print(json.dumps({
        "report": str(args.output_dir / "report.md"),
        "symbols": len(data),
        "configurations": len(evaluated),
        "champion": winner["config"].key,
        "train": winner["train"],
        "validation": validation,
        "gate": gate,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
