#!/usr/bin/env python3
"""Create conditional re-entry/reversal setups from recent expert signals."""

from __future__ import annotations

import json
import math
import statistics
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fetch_binance_market import _select_setup


BINANCE_BASE_URLS = (
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api.binance.us",
)
YAHOO_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"


def _mean(values: list[float]) -> float:
    return statistics.fmean(values)


def _sma(values: list[float], length: int) -> float:
    return _mean(values[-length:])


def _rsi(values: list[float], length: int = 14) -> float:
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    gains = [max(value, 0.0) for value in changes[-length:]]
    losses = [max(-value, 0.0) for value in changes[-length:]]
    average_loss = _mean(losses)
    if average_loss == 0:
        return 100.0
    relative_strength = _mean(gains) / average_loss
    return 100 - (100 / (1 + relative_strength))


def _atr(rows: list[dict[str, float]], length: int = 14) -> float:
    ranges = []
    for index in range(1, len(rows)):
        row = rows[index]
        previous_close = rows[index - 1]["close"]
        ranges.append(max(row["high"] - row["low"], abs(row["high"] - previous_close), abs(row["low"] - previous_close)))
    return _mean(ranges[-length:])


def _rounded_trade_levels(direction: str, entry: float, stop: float, min_rr: float) -> tuple[float, float, float]:
    """Round levels while keeping the published R/R at or above the configured minimum."""
    rounded_entry = round(entry, 8)
    rounded_stop = round(stop, 8)
    scale = 100_000_000
    if direction == "BUY":
        raw_target = rounded_entry + (rounded_entry - rounded_stop) * min_rr
        rounded_target = math.ceil(raw_target * scale) / scale
    else:
        raw_target = rounded_entry - (rounded_stop - rounded_entry) * min_rr
        rounded_target = math.floor(raw_target * scale) / scale
    return rounded_entry, rounded_stop, rounded_target


def _get_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "trading-session/2.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _binance_json(path: str) -> tuple[Any, str]:
    errors = []
    for base_url in BINANCE_BASE_URLS:
        try:
            return _get_json(f"{base_url}{path}"), base_url
        except Exception as exc:
            errors.append(f"{base_url}: {exc}")
    raise RuntimeError("all Binance endpoints failed: " + "; ".join(errors))


def _binance_rows(symbol: str, interval: str) -> list[dict[str, float]]:
    query = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": 90})
    payload, _ = _binance_json(f"/api/v3/klines?{query}")
    return [
        {"open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4]), "volume": float(row[5]), "closed_at": float(row[6]) / 1000}
        for row in payload[:-1]
    ]


def _yahoo_rows(symbol: str, interval: str) -> list[dict[str, float]]:
    yahoo_interval = {"15m": "15m", "1h": "60m", "4h": "60m"}[interval]
    query = urllib.parse.urlencode({"range": "60d", "interval": yahoo_interval, "includePrePost": "false"})
    encoded = urllib.parse.quote(symbol, safe="")
    payload = _get_json(f"{YAHOO_BASE_URL}/{encoded}?{query}")
    result = (payload.get("chart", {}).get("result") or [])[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators", {}).get("quote") or [{}])[0])
    rows = []
    for index, timestamp in enumerate(timestamps):
        values = {key: (quote.get(key) or [None] * len(timestamps))[index] for key in ("open", "high", "low", "close", "volume")}
        if any(values[key] is None for key in ("open", "high", "low", "close")):
            continue
        rows.append({
            "open": float(values["open"]), "high": float(values["high"]), "low": float(values["low"]),
            "close": float(values["close"]), "volume": float(values["volume"] or 0), "closed_at": float(timestamp),
        })
    # Yahoo has no native 4h interval. Aggregate closed 1h bars deterministically.
    if interval == "4h":
        aggregated = []
        for start in range(0, len(rows) - 3, 4):
            group = rows[start:start + 4]
            aggregated.append({
                "open": group[0]["open"], "high": max(row["high"] for row in group),
                "low": min(row["low"] for row in group), "close": group[-1]["close"],
                "volume": sum(row["volume"] for row in group), "closed_at": group[-1]["closed_at"],
            })
        rows = aggregated
    # Drop a possibly forming final bar.
    return rows[:-1]


def fetch_snapshot(asset: str, crypto_map: dict[str, str], yahoo_map: dict[str, str]) -> dict[str, Any] | None:
    if asset in crypto_map:
        market_symbol = crypto_map[asset]
        rows = {interval: _binance_rows(market_symbol, interval) for interval in ("15m", "1h", "4h")}
        ticker, endpoint = _binance_json(f"/api/v3/ticker/bookTicker?{urllib.parse.urlencode({'symbol': market_symbol})}")
        return {"provider": "binance_public_api", "market_symbol": market_symbol, "market_endpoint": endpoint, "bid": float(ticker["bidPrice"]), "ask": float(ticker["askPrice"]), "rows": rows}
    if asset in yahoo_map:
        market_symbol = yahoo_map[asset]
        rows = {interval: _yahoo_rows(market_symbol, interval) for interval in ("15m", "1h", "4h")}
        return {"provider": "yahoo_finance_chart", "market_symbol": market_symbol, "rows": rows}
    return None


def _trend(rows: list[dict[str, float]]) -> str:
    closes = [row["close"] for row in rows]
    fast, slow = _sma(closes, 20), _sma(closes, 50)
    if fast > slow * 1.0005:
        return "BUY"
    if fast < slow * 0.9995:
        return "SELL"
    return "NEUTRAL"


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _seed_candidates(candidates: list[dict[str, Any]], lookback_hours: int, now: datetime) -> list[dict[str, Any]]:
    cutoff = now - timedelta(hours=lookback_hours)
    eligible = []
    for candidate in candidates:
        timestamp = _parse_time(candidate.get("timestamp"))
        missing = set(candidate.get("missing") or [])
        if (
            candidate.get("expert_signal")
            and candidate.get("asset")
            and candidate.get("direction") in {"BUY", "SELL"}
            and timestamp and timestamp >= cutoff
            and not ({"broker_universe", "unknown_fbs_symbol"} & missing)
        ):
            eligible.append(candidate)
    return sorted(eligible, key=lambda item: _parse_time(item.get("timestamp")) or cutoff, reverse=True)


def build_derived_candidate(seed: dict[str, Any], snapshot: dict[str, Any], min_rr: float, allow_reversal: bool, now: datetime) -> tuple[dict[str, Any] | None, str]:
    rows_by_interval = snapshot.get("rows") or {}
    if any(len(rows_by_interval.get(interval) or []) < 52 for interval in ("15m", "1h", "4h")):
        return None, "insufficient_closed_candles"
    rows_15 = rows_by_interval["15m"]
    trends = {interval: _trend(rows_by_interval[interval]) for interval in ("15m", "1h", "4h")}
    higher_direction = trends["1h"] if trends["1h"] == trends["4h"] else "NEUTRAL"
    seed_direction = str(seed["direction"])
    if higher_direction == seed_direction:
        direction, origin = seed_direction, "reentry"
    elif allow_reversal and higher_direction in {"BUY", "SELL"} and higher_direction != seed_direction:
        direction, origin = higher_direction, "technical_reversal"
    else:
        return None, "higher_timeframes_not_aligned"
    if trends["15m"] not in {direction, "NEUTRAL"}:
        return None, "15m_opposes_higher_timeframes"

    closes_15 = [row["close"] for row in rows_15]
    rsi_values = {interval: _rsi([row["close"] for row in rows_by_interval[interval]]) for interval in ("15m", "1h", "4h")}
    if direction == "BUY" and (rsi_values["1h"] > 72 or rsi_values["4h"] > 70 or rsi_values["15m"] > 70):
        return None, "buy_overextended_rsi"
    if direction == "SELL" and (rsi_values["1h"] < 28 or rsi_values["4h"] < 30 or rsi_values["15m"] < 30):
        return None, "sell_overextended_rsi"

    volatility = _atr(rows_15)
    if volatility <= 0:
        return None, "invalid_atr"
    recent = rows_15[-20:]
    current = closes_15[-1]
    recent_high = max(row["high"] for row in recent[:-1])
    recent_low = min(row["low"] for row in recent[:-1])
    volumes = [row["volume"] for row in rows_15[-21:]]
    positive_volumes = [value for value in volumes[:-1] if value > 0]
    volume_ratio = volumes[-1] / _mean(positive_volumes) if positive_volumes and volumes[-1] > 0 else None
    if volume_ratio is not None and volume_ratio < 0.65:
        return None, "volume_confirmation_missing"

    if direction == "BUY":
        trigger = max(current, recent[-1]["high"] + 0.05 * volatility)
        entry = float(snapshot.get("ask") or trigger)
        entry = max(entry, trigger)
        stop = min(recent_low - 0.2 * volatility, entry - volatility)
        take_profit = entry + (entry - stop) * min_rr
        pending_order_type = "BUY STOP"
    else:
        trigger = min(current, recent[-1]["low"] - 0.05 * volatility)
        entry = float(snapshot.get("bid") or trigger)
        entry = min(entry, trigger)
        stop = max(recent_high + 0.2 * volatility, entry + volatility)
        take_profit = entry - (stop - entry) * min_rr
        pending_order_type = "SELL STOP"
    risk_percent = abs(entry - stop) / entry * 100 if entry else 100
    if risk_percent > 5:
        return None, "stop_distance_excessive"

    rounded_entry, rounded_stop, rounded_take_profit = _rounded_trade_levels(direction, entry, stop, min_rr)
    evidence = (
        f"Semilla {seed.get('channel')} {seed_direction}; tendencias 15m/1h/4h="
        f"{trends['15m']}/{trends['1h']}/{trends['4h']}; RSI="
        f"{rsi_values['15m']:.1f}/{rsi_values['1h']:.1f}/{rsi_values['4h']:.1f}; "
        f"ATR15={volatility:.8g}" + (f"; volumen relativo={volume_ratio:.2f}" if volume_ratio is not None else "; volumen no disponible en el proxy")
    )
    valid_until = (now + timedelta(hours=2)).isoformat()
    alternate_order_type = "BUY LIMIT" if pending_order_type == "BUY STOP" else "SELL LIMIT"
    order_instruction = (
        f"Intentar {pending_order_type} en {rounded_entry:.8g}; si FBS exige {alternate_order_type} para esa misma entrada, "
        "usarlo sin cambiar entrada, SL, TP ni lote."
    )
    invalidation = f"Cancelar la orden pendiente si no se activa antes de {valid_until}."
    return {
        "source": "telegram_derived", "provider": seed.get("channel") or seed.get("provider"),
        "asset": seed["asset"], "direction": direction, "entry": rounded_entry,
        "current_price": round(current, 8), "stop_loss": rounded_stop,
        "take_profits": [rounded_take_profit], "timestamp": now.isoformat(),
        "expert_signal": False, "candidate_origin": origin, "signal_status": "vigente",
        "analyst_status": "prevalidated", "execution_bias": "orden pendiente",
        "market_valid": True, "confidence": "medium", "quality_score": 3.5,
        "channel_priority": seed.get("channel_priority", 3), "seed_message_url": seed.get("message_url", ""),
        "seed_timestamp": seed.get("timestamp"), "pending_order_type": pending_order_type,
        "alternate_order_type": alternate_order_type,
        "order_instruction": order_instruction,
        "invalidation_condition": invalidation, "technical_evidence": evidence,
        "evidence": evidence, "valid_until": valid_until,
        "source_context": {"market_proxy": snapshot.get("provider"), "market_symbol": snapshot.get("market_symbol"), "seed_direction": seed_direction},
        "analysis": {"bid": snapshot.get("bid"), "ask": snapshot.get("ask"), "trend_15m": trends["15m"], "trend_1h": trends["1h"], "trend_4h": trends["4h"], "rsi_15m": round(rsi_values["15m"], 2), "rsi_1h": round(rsi_values["1h"], 2), "rsi_4h": round(rsi_values["4h"], 2), "atr_15m": round(volatility, 8), "volume_ratio_15m": round(volume_ratio, 4) if volume_ratio is not None else None},
        "missing": [],
    }, "accepted"


def build_market_scan_candidate(
    asset: str,
    snapshot: dict[str, Any],
    min_rr: float,
    now: datetime,
    validity_hours: int = 4,
) -> tuple[dict[str, Any] | None, str]:
    """Build a fully recalculated technical setup without attributing it to Telegram."""
    rows_by_interval = snapshot.get("rows") or {}
    if any(len(rows_by_interval.get(interval) or []) < 52 for interval in ("15m", "1h", "4h")):
        return None, "insufficient_closed_candles"

    rows_15 = rows_by_interval["15m"]
    closes = {interval: [row["close"] for row in rows_by_interval[interval]] for interval in ("15m", "1h", "4h")}
    trends = {interval: _trend(rows_by_interval[interval]) for interval in ("15m", "1h", "4h")}
    rsi_values = {interval: _rsi(closes[interval]) for interval in ("15m", "1h", "4h")}
    volatility = _atr(rows_15)
    if volatility <= 0:
        return None, "invalid_atr"

    current = closes["15m"][-1]
    recent = rows_15[-20:]
    recent_high = max(row["high"] for row in recent[:-1])
    recent_low = min(row["low"] for row in recent[:-1])
    range_position = (current - recent_low) / (recent_high - recent_low) if recent_high > recent_low else 0.5
    volumes = [row["volume"] for row in rows_15[-21:]]
    positive_volumes = [value for value in volumes[:-1] if value > 0]
    volume_ratio = volumes[-1] / _mean(positive_volumes) if positive_volumes and volumes[-1] > 0 else None

    setup = _select_setup(
        current=current,
        fast=_sma(closes["15m"], 12),
        slow=_sma(closes["15m"], 30),
        fast_1h=_sma(closes["1h"], 20),
        slow_1h=_sma(closes["1h"], 50),
        fast_4h=_sma(closes["4h"], 20),
        slow_4h=_sma(closes["4h"], 50),
        rsi_15m=rsi_values["15m"],
        rsi_1h=rsi_values["1h"],
        rsi_4h=rsi_values["4h"],
        volume_ratio=volume_ratio if volume_ratio is not None else 1.0,
        range_position=range_position,
        recent_high=recent_high,
        recent_low=recent_low,
        volatility=volatility,
        min_rr=min_rr,
    )
    setup_tier = "strict"

    if setup is None:
        directional_votes = {
            direction: sum(trends[interval] == direction for interval in ("15m", "1h", "4h"))
            for direction in ("BUY", "SELL")
        }
        direction = max(directional_votes, key=directional_votes.get)
        higher_support = trends["4h"] == direction and trends["1h"] in {direction, "NEUTRAL"}
        multi_timeframe_support = directional_votes[direction] >= 2 and trends["4h"] != ("SELL" if direction == "BUY" else "BUY")
        overextended = (
            direction == "BUY" and (rsi_values["15m"] > 70 or rsi_values["1h"] > 72 or rsi_values["4h"] > 72)
        ) or (
            direction == "SELL" and (rsi_values["15m"] < 30 or rsi_values["1h"] < 28 or rsi_values["4h"] < 28)
        )
        if not (higher_support or multi_timeframe_support):
            return None, "multi_timeframe_confirmation_missing"
        if overextended:
            return None, "market_scan_overextended_rsi"
        if volume_ratio is not None and volume_ratio < 0.65:
            return None, "volume_confirmation_missing"
        setup = {
            "setup_type": "conditional_confirmation",
            "execution_bias": "solo con activación de la orden pendiente",
            "direction": direction,
            "condition": "dos marcos apoyan la dirección y la entrada exige ruptura confirmatoria de 15m",
        }
        setup_tier = "conditional"

    direction = str(setup["direction"])
    setup_type = str(setup["setup_type"])
    if setup_type == "pullback":
        if direction == "BUY":
            entry = min(current - 0.25 * volatility, float(snapshot.get("ask") or current))
            stop = min(recent_low - 0.2 * volatility, entry - volatility)
            pending_order_type = "BUY LIMIT"
        else:
            entry = max(current + 0.25 * volatility, float(snapshot.get("bid") or current))
            stop = max(recent_high + 0.2 * volatility, entry + volatility)
            pending_order_type = "SELL LIMIT"
    else:
        if direction == "BUY":
            trigger = recent[-1]["high"] + 0.05 * volatility
            entry = max(trigger, float(snapshot.get("ask") or trigger))
            stop = min(recent_low - 0.2 * volatility, entry - volatility)
            pending_order_type = "BUY STOP"
        else:
            trigger = recent[-1]["low"] - 0.05 * volatility
            entry = min(trigger, float(snapshot.get("bid") or trigger))
            stop = max(recent_high + 0.2 * volatility, entry + volatility)
            pending_order_type = "SELL STOP"

    risk_percent = abs(entry - stop) / entry * 100 if entry else 100
    if risk_percent > 5:
        return None, "stop_distance_excessive"
    take_profit = entry + (entry - stop) * min_rr if direction == "BUY" else entry - (stop - entry) * min_rr
    rounded_entry, rounded_stop, rounded_take_profit = _rounded_trade_levels(direction, entry, stop, min_rr)
    valid_until = (now + timedelta(hours=max(2, validity_hours))).isoformat()
    alternate_order_type = "BUY LIMIT" if pending_order_type == "BUY STOP" else "BUY STOP" if pending_order_type == "BUY LIMIT" else "SELL LIMIT" if pending_order_type == "SELL STOP" else "SELL STOP"
    order_instruction = (
        f"Intentar {pending_order_type} en {rounded_entry:.8g}; si FBS exige {alternate_order_type} para esa misma entrada, "
        "usarlo sin cambiar entrada, SL, TP ni lote."
    )
    spread = None
    if snapshot.get("bid") is not None and snapshot.get("ask") is not None:
        spread = float(snapshot["ask"]) - float(snapshot["bid"])
    evidence = (
        f"Scanner técnico {setup_type} ({setup_tier}); tendencias 15m/1h/4h="
        f"{trends['15m']}/{trends['1h']}/{trends['4h']}; RSI="
        f"{rsi_values['15m']:.1f}/{rsi_values['1h']:.1f}/{rsi_values['4h']:.1f}; "
        f"ATR15={volatility:.8g}; posición_rango={range_position:.2f}"
        + (f"; volumen_relativo={volume_ratio:.2f}" if volume_ratio is not None else "; volumen no disponible en el proxy")
        + f"; condición={setup.get('condition')}"
    )
    alignment_score = directional_votes[direction] if setup_tier == "conditional" else sum(trends[interval] == direction for interval in ("15m", "1h", "4h"))
    quality_score = 3.0 + min(1.0, alignment_score / 3) + min(1.0, volume_ratio or 0.75)
    return {
        "source": "technical_market_scan", "provider": snapshot.get("provider") or "market_scanner",
        "asset": asset, "direction": direction, "entry": rounded_entry,
        "current_price": round(current, 8), "stop_loss": rounded_stop,
        "take_profits": [rounded_take_profit], "timestamp": now.isoformat(),
        "expert_signal": False, "candidate_origin": "market_scan", "signal_status": "vigente",
        "analyst_status": "prevalidated", "execution_bias": setup.get("execution_bias"),
        "market_valid": True, "confidence": "high" if setup_tier == "strict" else "medium",
        "quality_score": round(quality_score, 4), "channel_priority": 3,
        "setup_type": setup_type, "pending_order_type": pending_order_type,
        "alternate_order_type": alternate_order_type, "order_instruction": order_instruction,
        "invalidation_condition": f"Cancelar la orden pendiente si no se activa antes de {valid_until}.",
        "technical_evidence": evidence, "evidence": evidence, "valid_until": valid_until,
        "source_context": {"market_proxy": snapshot.get("provider"), "market_symbol": snapshot.get("market_symbol"), "scan_tier": setup_tier},
        "analysis": {
            "bid": snapshot.get("bid"), "ask": snapshot.get("ask"), "spread": round(spread, 8) if spread is not None else None,
            "trend_15m": trends["15m"], "trend_1h": trends["1h"], "trend_4h": trends["4h"],
            "rsi_15m": round(rsi_values["15m"], 2), "rsi_1h": round(rsi_values["1h"], 2), "rsi_4h": round(rsi_values["4h"], 2),
            "atr_15m": round(volatility, 8), "volume_ratio_15m": round(volume_ratio, 4) if volume_ratio is not None else None,
            "range_position_20": round(range_position, 4),
        },
        "missing": [],
    }, "accepted"


def derive_opportunities(
    candidates: list[dict[str, Any]], params: dict[str, Any], crypto_map: dict[str, str], yahoo_map: dict[str, str],
    *, snapshot_fetcher: Callable[[str, dict[str, str], dict[str, str]], dict[str, Any] | None] = fetch_snapshot,
    scan_assets: list[str] | None = None,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    settings = params.get("fallback_opportunities") or {}
    target = int(settings.get("target_primary_candidates", 3))
    if settings.get("enabled", True) is False:
        return [], {"target": target, "attempted": 0, "accepted": 0, "rejections": []}
    now = now or datetime.now(timezone.utc)
    minimum_rr = float(settings.get("min_rr", params.get("min_rr", 1.6)))

    def is_complete_valid(item: dict[str, Any]) -> bool:
        missing = set(item.get("missing") or [])
        if missing & {"asset", "direction", "entry", "stop_loss", "take_profit", "market_data", "broker_universe", "unknown_fbs_symbol"}:
            return False
        if item.get("market_valid") is False or item.get("signal_status") in {"vencida", "duplicada", "incompleta", "descartada", "llegada_tarde"}:
            return False
        entry, stop, targets, direction = item.get("entry"), item.get("stop_loss"), item.get("take_profits") or [], item.get("direction")
        if entry is None or stop is None or not targets or direction not in {"BUY", "SELL"}:
            return False
        risk = float(entry) - float(stop) if direction == "BUY" else float(stop) - float(entry)
        reward = float(targets[0]) - float(entry) if direction == "BUY" else float(entry) - float(targets[0])
        return risk > 0 and reward / risk >= minimum_rr

    valid_items = [item for item in candidates if is_complete_valid(item)]
    valid_assets = {str(item.get("asset")) for item in valid_items}
    needed = max(0, target - len(valid_assets))
    if needed == 0:
        return [], {"target": target, "attempted": 0, "accepted": 0, "rejections": []}

    derived, rejections, attempted_assets = [], [], set(valid_assets)
    seeds = _seed_candidates(candidates, int(settings.get("lookback_hours", 72)), now)
    for seed in seeds:
        asset = str(seed["asset"])
        if asset in attempted_assets:
            continue
        attempted_assets.add(asset)
        try:
            snapshot = snapshot_fetcher(asset, crypto_map, yahoo_map)
        except Exception as exc:
            rejections.append({"asset": asset, "reason": "market_data_error", "error": str(exc)})
            continue
        if not snapshot:
            rejections.append({"asset": asset, "reason": "market_proxy_unavailable"})
            continue
        candidate, reason = build_derived_candidate(
            seed, snapshot, minimum_rr,
            bool(settings.get("allow_reversal", True)), now,
        )
        if candidate:
            derived.append(candidate)
            if len(derived) >= needed:
                break
        else:
            rejections.append({"asset": asset, "reason": reason})

    market_settings = settings.get("market_scan") or {}
    market_attempted = 0
    market_accepted = 0
    pool_target = max(needed, int(market_settings.get("candidate_pool_size", 9)))
    remaining = max(0, pool_target - len(derived))
    if remaining and market_settings.get("enabled", True) is not False:
        universe = sorted(set(scan_assets or list(yahoo_map) + list(crypto_map)) - attempted_assets)
        max_assets = int(market_settings.get("max_assets", len(universe)))
        universe = universe[:max_assets]
        market_attempted = len(universe)
        snapshots: dict[str, dict[str, Any] | None] = {}
        workers = max(1, min(int(market_settings.get("max_workers", 8)), 16))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(snapshot_fetcher, asset, crypto_map, yahoo_map): asset for asset in universe}
            for future in as_completed(futures):
                asset = futures[future]
                try:
                    snapshots[asset] = future.result()
                except Exception as exc:
                    snapshots[asset] = None
                    rejections.append({"asset": asset, "reason": "market_data_error", "error": str(exc)})

        scan_candidates = []
        validity_hours = int(market_settings.get("validity_hours", 4))
        for asset in universe:
            snapshot = snapshots.get(asset)
            if not snapshot:
                if not any(item.get("asset") == asset and item.get("reason") == "market_data_error" for item in rejections):
                    rejections.append({"asset": asset, "reason": "market_proxy_unavailable"})
                continue
            candidate, reason = build_market_scan_candidate(asset, snapshot, minimum_rr, now, validity_hours)
            if candidate:
                scan_candidates.append(candidate)
            else:
                rejections.append({"asset": asset, "reason": reason})
        scan_candidates.sort(key=lambda item: (float(item.get("quality_score") or 0), str(item.get("asset"))), reverse=True)
        accepted_scan = scan_candidates[:remaining]
        derived.extend(accepted_scan)
        market_accepted = len(accepted_scan)

    return derived, {
        "target": target,
        "attempted": len(attempted_assets - valid_assets) + market_attempted,
        "accepted": len(derived),
        "rejections": rejections,
        "no_trade_slots": max(0, needed - len(derived)),
        "seeded_accepted": len(derived) - market_accepted,
        "market_scan_attempted": market_attempted,
        "market_scan_accepted": market_accepted,
    }
