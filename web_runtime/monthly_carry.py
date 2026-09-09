#!/usr/bin/env python3
"""Build the isolated monthly FX carry card from public point-in-time data.

The strategy is intentionally narrow: one card, evaluated once per month, and
never an order executor. Prices are Yahoo proxies and rates are lagged OECD
series distributed by FRED. Every executable value must be confirmed in FBS.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import io
import json
import math
import subprocess
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURJPY", "GBPJPY", "EURGBP", "AUDJPY", "EURAUD", "GBPAUD", "GBPCAD", "GBPCHF",
]
RATE_SERIES = {
    "USD": "IRSTCI01USM156N", "EUR": "IRSTCI01EZM156N", "GBP": "IRSTCI01GBM156N",
    "JPY": "IRSTCI01JPM156N", "CHF": "IRSTCI01CHM156N", "CAD": "IRSTCI01CAM156N",
    "AUD": "IRSTCI01AUM156N", "NZD": "IRSTCI01NZM156N",
}
QUOTE_USD_SYMBOL = {
    "EUR": ("EURUSD", False), "GBP": ("GBPUSD", False), "AUD": ("AUDUSD", False),
    "NZD": ("NZDUSD", False), "JPY": ("USDJPY", True), "CHF": ("USDCHF", True),
    "CAD": ("USDCAD", True),
}
RISK_USD = 50.0
RATE_LAG_DAYS = 45
MIN_RATE_GAP = 1.0
ATR_MULTIPLIER = 1.5
HOLD_TRADING_DAYS = 20
MAX_RATE_AGE_DAYS = 180


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_bytes(url: str, prefer_curl: bool = False) -> bytes:
    if prefer_curl:
        try:
            completed = subprocess.run(
                ["curl", "-L", "--fail", "--silent", "--show-error", url],
                check=True, capture_output=True, timeout=45,
            )
            return completed.stdout
        except Exception:
            pass
    request = urllib.request.Request(url, headers={"User-Agent": "trading-monthly-carry/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return response.read()
    except Exception as first_error:
        try:
            completed = subprocess.run(
                ["curl", "-L", "--fail", "--silent", "--show-error", url],
                check=True, capture_output=True, timeout=45,
            )
            return completed.stdout
        except Exception as second_error:
            raise RuntimeError(f"No se pudo descargar {url}: {first_error}; {second_error}") from second_error


def yahoo(symbol: str) -> dict[str, Any]:
    ticker = urllib.parse.quote(f"{symbol}=X", safe="")
    query = urllib.parse.urlencode({"range": "6mo", "interval": "1d", "includePrePost": "false"})
    payload = json.loads(get_bytes(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?{query}"))
    result = (((payload.get("chart") or {}).get("result") or [None])[0])
    if not result:
        raise RuntimeError(f"Yahoo no devolvió datos para {symbol}")
    stamps = result.get("timestamp") or []
    quote = (((result.get("indicators") or {}).get("quote") or [{}])[0])
    bars = []
    for index, stamp in enumerate(stamps):
        values = [quote.get(field, [None] * len(stamps))[index] for field in ("open", "high", "low", "close")]
        if any(value is None for value in values):
            continue
        bars.append({
            "date": datetime.fromtimestamp(int(stamp), timezone.utc).date(),
            "open": float(values[0]), "high": float(values[1]), "low": float(values[2]), "close": float(values[3]),
        })
    meta = result.get("meta") or {}
    current = meta.get("regularMarketPrice") or (bars[-1]["close"] if bars else None)
    if len(bars) < 20 or current is None:
        raise RuntimeError(f"Historial diario insuficiente para {symbol}")
    return {"bars": bars, "current": float(current), "proxy_symbol": f"{symbol}=X"}


def rates_for(day: date) -> tuple[dict[str, float], dict[str, str]]:
    cutoff = day - timedelta(days=RATE_LAG_DAYS)
    values: dict[str, float] = {}
    observations: dict[str, str] = {}
    for currency, series_id in RATE_SERIES.items():
        content = get_bytes(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}", prefer_curl=True).decode()
        rows = []
        for row in csv.DictReader(io.StringIO(content)):
            try:
                rows.append((date.fromisoformat(row["observation_date"]), float(row[series_id])))
            except (KeyError, TypeError, ValueError):
                continue
        dates = [item[0] for item in rows]
        index = bisect.bisect_right(dates, cutoff) - 1
        if index < 0:
            raise RuntimeError(f"No hay tasa conocida para {currency} al {cutoff}")
        values[currency] = rows[index][1]
        observations[currency] = rows[index][0].isoformat()
    return values, observations


def atr(bars: list[dict[str, Any]], through: int, length: int = 14) -> float:
    if through < length:
        raise RuntimeError("No hay velas suficientes para ATR(14)")
    ranges = []
    for index in range(through - length + 1, through + 1):
        previous = bars[index - 1]["close"]
        current = bars[index]
        ranges.append(max(current["high"] - current["low"], abs(current["high"] - previous), abs(current["low"] - previous)))
    return sum(ranges) / length


def quote_to_usd(currency: str, market: dict[str, dict[str, Any]]) -> float:
    if currency == "USD":
        return 1.0
    symbol, inverse = QUOTE_USD_SYMBOL[currency]
    if symbol not in market:
        market[symbol] = yahoo(symbol)
    price = market[symbol]["current"]
    return 1.0 / price if inverse else price


def lot_size(symbol: str, entry: float, stop: float, market: dict[str, dict[str, Any]]) -> tuple[float, float]:
    conversion = quote_to_usd(symbol[3:], market)
    risk_per_lot = abs(entry - stop) * 100_000 * conversion
    if risk_per_lot <= 0:
        raise RuntimeError("No se pudo calcular el lotaje")
    raw = math.floor((RISK_USD / risk_per_lot) * 100) / 100
    lots = max(0.01, raw)
    return lots, round(risk_per_lot * lots, 2)


def next_month_weekday(day: date) -> date:
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    candidate = date(year, month, 1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def no_trade(now: datetime, reason: str, next_review: date) -> dict[str, Any]:
    month = now.strftime("%Y-%m")
    return {
        "schema_version": 1, "run_id": f"monthly-carry-{month}", "date": now.date().isoformat(),
        "generated_at": now.isoformat(), "status": "completed", "strategy_type": "monthly_carry",
        "summary": {"symbols_scanned": len(SYMBOLS), "valid_candidates": 0, "cadence": "monthly"},
        "cards": [{
            "id": f"monthly-carry-{month}-wait", "rank": 1, "status": "NO_TRADE", "asset": "NO TRADE",
            "direction": "WAIT", "stars": 0, "reasons": [reason], "next_review": next_review.isoformat(),
            "strategy_type": "monthly_carry", "monitorable": False,
        }],
    }


def build(now: datetime | None = None) -> dict[str, Any]:
    now = now or utc_now()
    calendar = yahoo("EURUSD")["bars"]
    month_days = sorted({bar["date"] for bar in calendar if (bar["date"].year, bar["date"].month) == (now.year, now.month)})
    next_review = next_month_weekday(now.date())
    if not month_days:
        return no_trade(now, "El mercado todavía no publicó la primera vela hábil del mes.", now.date())
    first_day = month_days[0]
    expected_second_day = first_day + timedelta(days=1)
    while expected_second_day.weekday() >= 5:
        expected_second_day += timedelta(days=1)
    second_day = month_days[1] if len(month_days) > 1 else expected_second_day
    if now.date() == first_day:
        return no_trade(now, "La señal se confirma al cierre del primer día hábil; volver a consultar el segundo.", second_day)
    if now.date() != second_day:
        return no_trade(now, f"La ventana de entrada de este mes está cerrada. Próxima evaluación: {next_review.isoformat()}.", next_review)

    signal_day = first_day
    rates, rate_dates = rates_for(signal_day)
    ranked = []
    for symbol in SYMBOLS:
        if any((signal_day - date.fromisoformat(rate_dates[currency])).days > MAX_RATE_AGE_DAYS for currency in (symbol[:3], symbol[3:])):
            continue
        gap = rates[symbol[:3]] - rates[symbol[3:]]
        if abs(gap) >= MIN_RATE_GAP:
            ranked.append((abs(gap), symbol, "BUY" if gap > 0 else "SELL", gap))
    if not ranked:
        return no_trade(now, "Ningún par supera la diferencia mínima de tasas de 1 punto porcentual.", next_review)
    _, symbol, direction, gap = sorted(ranked, key=lambda row: (-row[0], row[1]))[0]
    market: dict[str, dict[str, Any]] = {symbol: yahoo(symbol)}
    bars = market[symbol]["bars"]
    signal_index = next((index for index, bar in enumerate(bars) if bar["date"] == signal_day), None)
    if signal_index is None:
        raise RuntimeError("No se encontró la vela de señal")
    daily_atr = atr(bars, signal_index)
    entry = market[symbol]["current"]
    risk = daily_atr * ATR_MULTIPLIER
    stop = entry - risk if direction == "BUY" else entry + risk
    target = entry + risk if direction == "BUY" else entry - risk
    lots, actual_risk = lot_size(symbol, entry, stop, market)
    decimals = 3 if symbol.endswith("JPY") else 5
    valid_until = datetime.combine(second_day, datetime.max.time(), timezone.utc).isoformat()
    month = now.strftime("%Y-%m")
    return {
        "schema_version": 1, "run_id": f"monthly-carry-{month}", "date": now.date().isoformat(),
        "generated_at": now.isoformat(), "status": "completed", "strategy_type": "monthly_carry",
        "summary": {"symbols_scanned": len(SYMBOLS), "valid_candidates": 1, "cadence": "monthly", "risk_usd": actual_risk},
        "cards": [{
            "id": f"monthly-carry-{month}-{symbol.lower()}", "rank": 1, "stars": 5,
            "asset": symbol, "direction": direction, "order_type": "MARKET",
            "entry": round(entry, decimals), "current_price": round(entry, decimals),
            "stop_loss": round(stop, decimals), "take_profit": round(target, decimals),
            "take_profits": [round(target, decimals)], "risk_reward": 1.0,
            "risk_usd": actual_risk, "size": f"{lots:.2f} lot", "valid_until": valid_until,
            "entry_valid_until": valid_until, "management_horizon_trading_days": HOLD_TRADING_DAYS,
            "strategy_type": "monthly_carry", "cadence": "monthly", "monitorable": True,
            "source": "carry mensual validado · Yahoo + OECD/FRED (45 días de retraso)",
            "provider": "yahoo_finance_proxy", "proxy_symbol": market[symbol]["proxy_symbol"],
            "target_basis": "1R desde 1.5 × ATR diario",
            "rate_gap": round(gap, 3), "base_rate": rates[symbol[:3]], "quote_rate": rates[symbol[3:]],
            "rate_observations": {symbol[:3]: rate_dates[symbol[:3]], symbol[3:]: rate_dates[symbol[3:]]},
            "instruction": "Confirmar bid/ask, spread y swap long/short en FBS antes de abrir. No duplicar esta entrada durante el mes.",
            "reasons": [f"Diferencial de tasas {gap:+.2f} pp", "Mayor diferencial elegible entre 15 pares", "Horizonte máximo: 20 días hábiles"],
        }],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "generated", "cards": len(payload["cards"]), "actionable": payload["summary"]["valid_candidates"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
