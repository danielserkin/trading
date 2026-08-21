#!/usr/bin/env python3
"""Validate and publish active-trade management actions to Telegram."""

from __future__ import annotations

import argparse
import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

ACTIONS = {"MANTENER", "MOVER_SL", "AJUSTAR_TP", "CIERRE_PARCIAL", "CERRAR_TODO", "EVIDENCIA_INSUFICIENTE"}
DIRECTIONS = {"BUY", "SELL"}
CONFIDENCE = {"alta", "media", "baja"}


def _number(item: dict[str, Any], key: str, required: bool = False) -> float | None:
    value = item.get(key)
    if value is None:
        if required:
            raise ValueError(f"{key} is required")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    value = float(value)
    if value <= 0 and key != "current_profit_usd":
        raise ValueError(f"{key} must be greater than zero")
    return value


def validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    positions = payload.get("positions")
    if not isinstance(positions, list) or not positions:
        raise ValueError("positions must be a non-empty array")
    for index, item in enumerate(positions, 1):
        if not isinstance(item, dict):
            raise ValueError(f"position {index} must be an object")
        for key in ("asset", "action", "instruction", "confidence"):
            if not str(item.get(key, "")).strip():
                raise ValueError(f"position {index}: {key} is required")
        action = str(item["action"]).upper()
        direction = str(item.get("direction", "")).upper()
        confidence = str(item["confidence"]).lower()
        if action not in ACTIONS:
            raise ValueError(f"position {index}: unsupported action {action}")
        if direction and direction not in DIRECTIONS:
            raise ValueError(f"position {index}: direction must be BUY or SELL")
        if action != "EVIDENCIA_INSUFICIENTE" and direction not in DIRECTIONS:
            raise ValueError(f"position {index}: direction is required")
        if confidence not in CONFIDENCE:
            raise ValueError(f"position {index}: confidence must be alta, media, or baja")
        reasons = item.get("reasons", [])
        if not isinstance(reasons, list) or any(not str(reason).strip() for reason in reasons):
            raise ValueError(f"position {index}: reasons must be an array of text")
        item.update(action=action, direction=direction, confidence=confidence)
        volume = _number(item, "volume")
        old_sl, old_tp = _number(item, "old_sl"), _number(item, "old_tp")
        new_sl, new_tp = _number(item, "new_sl"), _number(item, "new_tp")
        current = _number(item, "current_price")
        if action == "MOVER_SL" and new_sl is None:
            raise ValueError(f"position {index}: new_sl is required for MOVER_SL")
        if action == "AJUSTAR_TP" and new_tp is None:
            raise ValueError(f"position {index}: new_tp is required for AJUSTAR_TP")
        if new_sl is not None:
            if old_sl is None or current is None:
                raise ValueError(f"position {index}: old_sl and current_price are required with new_sl")
            if direction == "BUY" and (new_sl < old_sl or new_sl >= current):
                raise ValueError(f"position {index}: BUY new_sl must not widen risk and must remain below current price")
            if direction == "SELL" and (new_sl > old_sl or new_sl <= current):
                raise ValueError(f"position {index}: SELL new_sl must not widen risk and must remain above current price")
        if new_tp is not None:
            if old_tp is None or current is None:
                raise ValueError(f"position {index}: old_tp and current_price are required with new_tp")
            if direction == "BUY" and (new_tp > old_tp or new_tp <= current):
                raise ValueError(f"position {index}: BUY new_tp must be closer than old_tp and above current price")
            if direction == "SELL" and (new_tp < old_tp or new_tp >= current):
                raise ValueError(f"position {index}: SELL new_tp must be closer than old_tp and below current price")
        if action == "CIERRE_PARCIAL":
            close_volume = _number(item, "close_volume", required=True)
            remaining = _number(item, "remaining_volume", required=True)
            if volume is None:
                raise ValueError(f"position {index}: volume is required for CIERRE_PARCIAL")
            if abs((close_volume or 0) + (remaining or 0) - volume) > 1e-8:
                raise ValueError(f"position {index}: close_volume + remaining_volume must equal volume")
    return payload


def _fmt(value: Any, digits: int = 5) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def build_message(payload: dict[str, Any]) -> str:
    validate_payload(payload)
    lines = ["🛡️ <b>GESTIÓN DE TRADES ACTIVOS · FBS</b>", "━━━━━━━━━━━━━━━━━━━━"]
    for item in payload["positions"]:
        asset = html.escape(str(item["asset"]).upper())
        ticket = html.escape(str(item.get("ticket") or "sin ticket"))
        direction = html.escape(str(item.get("direction") or "—"))
        action = html.escape(str(item["action"]).replace("_", " "))
        urgency = html.escape(str(item.get("urgency") or "AHORA"))
        lines += [f"\n📌 <b>{asset} {direction}</b> · <code>{ticket}</code>", f"🚦 <b>{action}</b> · {urgency}", f"⚡ {html.escape(str(item['instruction']))}"]
        facts = []
        if item.get("volume") is not None:
            facts.append(f"Vol. {_fmt(item['volume'], 2)}")
        if item.get("entry") is not None:
            facts.append(f"Entrada {_fmt(item['entry'])}")
        if item.get("current_price") is not None:
            facts.append(f"Actual {_fmt(item['current_price'])}")
        if facts:
            lines.append("📍 " + " · ".join(facts))
        changes = []
        if item.get("new_sl") is not None:
            changes.append(f"SL {_fmt(item.get('old_sl'))} → <b>{_fmt(item['new_sl'])}</b>")
        if item.get("new_tp") is not None:
            changes.append(f"TP {_fmt(item.get('old_tp'))} → <b>{_fmt(item['new_tp'])}</b>")
        if item.get("close_volume") is not None:
            changes.append(f"Cerrar <b>{_fmt(item['close_volume'], 2)}</b> · Restan {_fmt(item.get('remaining_volume'), 2)}")
        if changes:
            lines.append("🎯 " + " | ".join(changes))
        if item.get("current_profit_usd") is not None:
            lines.append(f"💵 Resultado visible: <b>${float(item['current_profit_usd']):.2f}</b>")
        lines += [f"• {html.escape(str(reason))}" for reason in item.get("reasons", [])[:3]]
        lines.append(f"🔎 Confianza: <b>{html.escape(str(item['confidence']).upper())}</b>")
    lines += ["\n━━━━━━━━━━━━━━━━━━━━", "🤖 Recomendación informativa. Ejecutar y confirmar manualmente en FBS."]
    message = "\n".join(lines)
    if len(message) > 4096:
        raise ValueError("Telegram message exceeds 4096 characters")
    return message


def send_message(token: str, chat_id: str, message: str) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode()
    request = urllib.request.Request(url, data=body, headers={"User-Agent": "active-trade-manager/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Telegram Bot API HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Telegram Bot API network error: {exc.reason}") from None
    if not result.get("ok"):
        raise RuntimeError(str(result.get("description") or "Telegram delivery failed"))
    return result.get("result") or {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish validated active-trade management actions.")
    parser.add_argument("--payload-json", required=True, help="JSON object containing reviewed_at and positions")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        payload = validate_payload(json.loads(args.payload_json))
        message = build_message(payload)
        if args.dry_run:
            print(json.dumps({"status": "dry_run", "message": message}, ensure_ascii=False, indent=2))
            return 0
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_TARGET_CHAT_ID", "").strip()
        if not token or not chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_TARGET_CHAT_ID are required")
        sent = send_message(token, chat_id, message)
        print(json.dumps({"status": "sent", "message_id": sent.get("message_id")}, ensure_ascii=False))
        return 0
    except (ValueError, json.JSONDecodeError, RuntimeError) as exc:
        print(json.dumps({"status": "delivery_failed", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
