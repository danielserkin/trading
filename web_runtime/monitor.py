#!/usr/bin/env python3
"""Deterministic, public-data active trade monitor.

This module never connects to a broker and never executes orders. Public quotes
are supporting proxies; every instruction explicitly asks the user to confirm it
in FBS.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SESSION_SCRIPTS = ROOT / "skills" / "trading-session" / "scripts"
MANAGER_SCRIPTS = ROOT / "skills" / "active-trade-manager" / "scripts"
sys.path[:0] = [str(SESSION_SCRIPTS), str(MANAGER_SCRIPTS)]

from run_crypto_web_session import FBS_CRYPTO_SYMBOL_MAP  # noqa: E402
from run_telegram_fbs_session import YAHOO_PROXY_SYMBOLS  # noqa: E402
from publish_active_trade_action import build_message, send_message, validate_payload  # noqa: E402


@dataclass(frozen=True)
class Candle:
    opened_at: datetime
    closed_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def get_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "trading-dashboard-monitor/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def binance_candles(symbol: str, interval: str, limit: int = 160) -> list[Candle]:
    query = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": limit})
    rows = get_json(f"https://api.binance.com/api/v3/klines?{query}")
    now_ms = int(utc_now().timestamp() * 1000)
    return [
        Candle(
            opened_at=datetime.fromtimestamp(row[0] / 1000, timezone.utc),
            closed_at=datetime.fromtimestamp(row[6] / 1000, timezone.utc),
            open=float(row[1]), high=float(row[2]), low=float(row[3]), close=float(row[4]), volume=float(row[5]),
        )
        for row in rows
        if int(row[6]) < now_ms
    ]


def yahoo_candles(symbol: str, interval: str, range_value: str) -> list[Candle]:
    encoded = urllib.parse.quote(symbol, safe="")
    query = urllib.parse.urlencode({"interval": interval, "range": range_value, "includePrePost": "false"})
    payload = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?{query}")
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        raise ValueError(f"Yahoo returned no candles for {symbol}")
    timestamps = result.get("timestamp") or []
    quote = (((result.get("indicators") or {}).get("quote") or [{}])[0])
    seconds = 900 if interval == "15m" else 3600
    now = utc_now()
    candles = []
    for index, stamp in enumerate(timestamps):
        values = [quote.get(key, [None] * len(timestamps))[index] for key in ("open", "high", "low", "close")]
        if any(value is None for value in values):
            continue
        opened = datetime.fromtimestamp(stamp, timezone.utc)
        closed = opened + timedelta(seconds=seconds)
        if closed >= now:
            continue
        candles.append(Candle(opened, closed, *(float(value) for value in values), float((quote.get("volume") or [0] * len(timestamps))[index] or 0)))
    return candles


def aggregate(candles: list[Candle], size: int) -> list[Candle]:
    result = []
    for index in range(0, len(candles) - size + 1, size):
        rows = candles[index:index + size]
        result.append(Candle(rows[0].opened_at, rows[-1].closed_at, rows[0].open, max(row.high for row in rows), min(row.low for row in rows), rows[-1].close, sum(row.volume for row in rows)))
    return result


def market_snapshot(monitor: dict[str, Any]) -> dict[str, Any]:
    asset = str(monitor.get("asset") or "").upper()
    if asset in FBS_CRYPTO_SYMBOL_MAP:
        symbol = FBS_CRYPTO_SYMBOL_MAP[asset]
        return {
            "provider": "binance_spot_proxy",
            "proxy_symbol": symbol,
            "m15": binance_candles(symbol, "15m"),
            "h1": binance_candles(symbol, "1h"),
            "h4": binance_candles(symbol, "4h"),
        }
    symbol = str(monitor.get("proxy_symbol") or YAHOO_PROXY_SYMBOLS.get(asset) or "")
    if not symbol:
        raise ValueError(f"No public proxy configured for {asset}")
    hourly = yahoo_candles(symbol, "60m", "1mo")
    return {
        "provider": "yahoo_finance_proxy",
        "proxy_symbol": symbol,
        "m15": yahoo_candles(symbol, "15m", "5d"),
        "h1": hourly,
        "h4": aggregate(hourly, 4),
    }


def ema(values: list[float], length: int) -> float:
    if len(values) < length:
        raise ValueError(f"Need {length} values for EMA")
    factor = 2 / (length + 1)
    value = sum(values[:length]) / length
    for item in values[length:]:
        value = item * factor + value * (1 - factor)
    return value


def atr(candles: list[Candle], length: int = 14) -> float:
    if len(candles) < length + 1:
        raise ValueError("Not enough candles for ATR")
    ranges = []
    for previous, current in zip(candles[-length - 1:-1], candles[-length:]):
        ranges.append(max(current.high - current.low, abs(current.high - previous.close), abs(current.low - previous.close)))
    return sum(ranges) / len(ranges)


def rsi(candles: list[Candle], length: int = 14) -> float:
    changes = [b.close - a.close for a, b in zip(candles[-length - 1:-1], candles[-length:])]
    gains = sum(max(change, 0) for change in changes) / length
    losses = sum(max(-change, 0) for change in changes) / length
    return 100.0 if losses == 0 else 100 - (100 / (1 + gains / losses))


def trend(candles: list[Candle]) -> str:
    closes = [row.close for row in candles]
    current = ema(closes[-40:], 20)
    previous = ema(closes[-45:-5], 20)
    if closes[-1] > current and current > previous:
        return "BUY"
    if closes[-1] < current and current < previous:
        return "SELL"
    return "NEUTRAL"


def rounded(value: float, reference: float) -> float:
    if reference >= 100:
        digits = 2
    elif reference >= 10:
        digits = 3
    elif reference >= 1:
        digits = 5
    else:
        digits = 7
    return round(value, digits)


def decision_for(monitor: dict[str, Any], snapshot: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or utc_now()
    direction = str(monitor["direction"]).upper()
    entry = float(monitor["entry"])
    original_sl = float(monitor.get("original_sl") or monitor["stop_loss"])
    old_sl = float(monitor.get("current_sl") or monitor["stop_loss"])
    old_tp = float(monitor.get("current_tp") or monitor["take_profit"])
    m15, h1, h4 = snapshot["m15"], snapshot["h1"], snapshot["h4"]
    if len(m15) < 30 or len(h1) < 30 or len(h4) < 20:
        raise ValueError("Faltan velas cerradas M15/H1/H4")
    if now - m15[-1].closed_at > timedelta(minutes=35):
        raise ValueError("La última vela M15 está desactualizada")
    current = m15[-1].close
    initial_risk = abs(entry - original_sl)
    if initial_risk <= 0:
        raise ValueError("El riesgo inicial no es válido")
    favorable = current - entry if direction == "BUY" else entry - current
    target_path = old_tp - entry if direction == "BUY" else entry - old_tp
    current_r = favorable / initial_risk
    progress = favorable / target_path if target_path > 0 else 0
    atr15 = atr(m15)
    trends = {"m15": trend(m15), "h1": trend(h1), "h4": trend(h4)}
    against = "SELL" if direction == "BUY" else "BUY"
    activated = parse_time(monitor.get("activated_at")) or now
    age = now - activated
    valid_until = parse_time(monitor.get("valid_until"))
    base = {
        "evaluated_at": now.isoformat(),
        "candle_close": m15[-1].closed_at.isoformat(),
        "provider": snapshot["provider"],
        "proxy_symbol": snapshot["proxy_symbol"],
        "current_price": rounded(current, current),
        "current_r": round(current_r, 3),
        "progress": round(progress, 3),
        "atr15": rounded(atr15, current),
        "rsi15": round(rsi(m15), 1),
        "trends": trends,
        "confidence": "media" if snapshot["provider"] == "binance_spot_proxy" else "baja",
    }

    def finish(action: str, instruction: str, reasons: list[str], urgency: str = "PRÓXIMO PASO", **levels: Any) -> dict[str, Any]:
        return {**base, "action": action, "instruction": instruction, "reasons": reasons, "urgency": urgency, **levels}

    sl_hit = current <= old_sl if direction == "BUY" else current >= old_sl
    tp_hit = current >= old_tp if direction == "BUY" else current <= old_tp
    if sl_hit:
        return finish("CERRAR_TODO", "Verificar en FBS; si la posición continúa abierta, cerrarla a mercado.", ["El proxy cruzó el SL configurado", "No ampliar ni retirar el stop"], "AHORA")
    if tp_hit:
        return finish("CERRAR_TODO", "Verificar en FBS que el TP se ejecutó; si sigue abierta, cerrar el remanente.", ["El proxy alcanzó el TP", "Evitar devolver una ganancia ya conseguida"], "AHORA")
    if now.weekday() == 4 and now.hour >= 19:
        return finish("CERRAR_TODO", "Cerrar la posición antes del fin de semana tras confirmar el precio en FBS.", ["Cierre semanal próximo", "El seguimiento usa una estrategia intradía"], "AHORA")
    if valid_until and now >= valid_until:
        return finish("CERRAR_TODO", "Cerrar por vencimiento de la idea tras confirmar la cotización FBS.", ["La vigencia intradía original terminó", f"Progreso alcanzado: {progress:.0%}"], "AHORA")
    if valid_until and timedelta() <= valid_until - now <= timedelta(minutes=30) and progress < 0.75:
        return finish("CERRAR_TODO", "Cerrar antes del fin de la vigencia tras confirmar la cotización FBS.", [f"Restan {(valid_until-now).total_seconds()/60:.0f} min", f"Progreso menor al 75%: {progress:.0%}"], "AHORA")
    if age >= timedelta(hours=6) and current_r <= 0 and trends["m15"] == against:
        return finish("CERRAR_TODO", "Cerrar por falta prolongada de progreso y deterioro M15.", [f"Trade abierto {age.total_seconds()/3600:.1f} h", "Resultado no positivo y M15 contrario"], "AHORA")
    if trends["m15"] == against and trends["h1"] == against and current_r <= -0.35:
        return finish("CERRAR_TODO", "Cerrar tras confirmar que FBS muestra la misma invalidación.", ["M15 y H1 cambiaron contra la tesis", f"Retroceso de {current_r:.2f}R"], "AHORA")

    if current_r >= 1.0:
        if direction == "BUY":
            swing = min(row.low for row in m15[-6:-1]) - atr15 * 0.10
            proposed = max(entry, swing)
            valid = proposed > old_sl and proposed < current - atr15 * 0.15
        else:
            swing = max(row.high for row in m15[-6:-1]) + atr15 * 0.10
            proposed = min(entry, swing)
            valid = proposed < old_sl and proposed > current + atr15 * 0.15
        if valid:
            new_sl = rounded(proposed, current)
            return finish("MOVER_SL", f"Mover SL a {new_sl} después de confirmar el swing y spread en FBS.", [f"Avance de {current_r:.2f}R", "Swing M15 cerrado permite reducir riesgo"], "AHORA", new_sl=new_sl)

    if progress >= 0.45 and trends["m15"] == against and trends["h1"] in {against, "NEUTRAL"}:
        proposed_tp = current + atr15 * 0.55 if direction == "BUY" else current - atr15 * 0.55
        closer = proposed_tp < old_tp if direction == "BUY" else proposed_tp > old_tp
        beyond = proposed_tp > current if direction == "BUY" else proposed_tp < current
        if closer and beyond:
            new_tp = rounded(proposed_tp, current)
            return finish("AJUSTAR_TP", f"Acercar TP a {new_tp} tras confirmar el obstáculo en FBS.", [f"Progreso de {progress:.0%}", "M15 perdió impulso y H1 no confirma continuación"], new_tp=new_tp)

    reasons = [
        f"Estructura M15/H1/H4: {trends['m15']}/{trends['h1']}/{trends['h4']}",
        f"Progreso {progress:.0%} · resultado {current_r:.2f}R",
    ]
    return finish("MANTENER", "Mantener SL y TP actuales; confirmar que los niveles siguen iguales en FBS.", reasons)


def insufficient_decision(monitor: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "evaluated_at": utc_now().isoformat(),
        "action": "EVIDENCIA_INSUFICIENTE",
        "instruction": "No modificar la operación con estos datos; revisar FBS manualmente.",
        "reasons": [message],
        "confidence": "baja",
        "urgency": "REVISAR",
    }


def telegram_item(monitor: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    item = {
        "asset": monitor.get("asset"),
        "ticket": monitor.get("ticket") or monitor.get("trade_id"),
        "direction": monitor.get("direction"),
        "action": decision["action"],
        "urgency": decision.get("urgency"),
        "instruction": decision["instruction"],
        "reasons": decision.get("reasons", []),
        "confidence": decision.get("confidence", "baja"),
        "entry": monitor.get("entry"),
        "volume": monitor.get("volume"),
        "current_price": decision.get("current_price"),
        "old_sl": monitor.get("current_sl") or monitor.get("stop_loss"),
        "old_tp": monitor.get("current_tp") or monitor.get("take_profit"),
    }
    if decision.get("new_sl") is not None:
        item["new_sl"] = decision["new_sl"]
    if decision.get("new_tp") is not None:
        item["new_tp"] = decision["new_tp"]
    return item


def run(state: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    results = []
    telegram_positions = []
    for trade_id, monitor in (state.get("monitors") or {}).items():
        if not monitor.get("enabled"):
            continue
        try:
            decision = decision_for(monitor, market_snapshot(monitor))
        except Exception as exc:
            decision = insufficient_decision(monitor, str(exc))
        result = {"trade_id": trade_id, "activation_id": monitor.get("activation_id"), "decision": decision, "terminal": False}
        results.append(result)
        previous = monitor.get("last_decision") or {}
        if previous.get("candle_close") != decision.get("candle_close") or decision["action"] == "EVIDENCIA_INSUFICIENTE":
            telegram_positions.append(telegram_item({**monitor, "trade_id": trade_id}, decision))

    telegram = {"status": "not_needed"}
    if telegram_positions:
        payload = validate_payload({"reviewed_at": utc_now().isoformat(), "positions": telegram_positions})
        message = build_message(payload)
        if dry_run:
            telegram = {"status": "dry_run", "message": message}
        else:
            import os
            token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN", "").strip(), os.getenv("TELEGRAM_TARGET_CHAT_ID", "").strip()
            if not token or not chat_id:
                telegram = {"status": "not_configured"}
            else:
                try:
                    sent = send_message(token, chat_id, message)
                    telegram = {"status": "sent", "message_id": sent.get("message_id")}
                except Exception as exc:
                    telegram = {"status": "delivery_failed", "error": str(exc)}
    level = "error" if telegram["status"] == "delivery_failed" else "info"
    events = [{"level": level, "message": f"📡 {len(results)} trade(s) evaluados · Telegram {telegram['status']}"}]
    return {"generated_at": utc_now().isoformat(), "results": results, "telegram": telegram, "events": events}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = run(json.loads(args.state.read_text()), args.dry_run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "completed", "monitors": len(result["results"]), "telegram": result["telegram"]["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
