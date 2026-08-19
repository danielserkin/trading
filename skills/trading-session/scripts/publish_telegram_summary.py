#!/usr/bin/env python3
"""Configure Telegram Bot API delivery and publish a compact session summary."""

from __future__ import annotations

import argparse
import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from score_candidates import rank_candidates, reason_label, risk_reward


def bot_api(token: str, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    encoded = urllib.parse.urlencode(payload or {}).encode("utf-8")
    request = urllib.request.Request(url, data=encoded if payload else None, headers={"User-Agent": "trading-session/2.0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Telegram Bot API HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Telegram Bot API network error: {exc.reason}") from None
    if not result.get("ok"):
        raise RuntimeError(str(result.get("description") or "Telegram Bot API request failed"))
    return result


def discover_channels(token: str) -> list[dict[str, Any]]:
    updates = bot_api(token, "getUpdates").get("result") or []
    channels = {}
    for update in updates:
        post = update.get("channel_post") or update.get("edited_channel_post") or {}
        chat = post.get("chat") or {}
        if chat.get("id") is not None:
            channels[str(chat["id"])] = {"chat_id": chat["id"], "title": chat.get("title", ""), "type": chat.get("type", "")}
    return list(channels.values())


def _candidate_line(rank: int, candidate: dict[str, Any]) -> str:
    rr = risk_reward(candidate)
    tp = (candidate.get("take_profits") or ["-"])[0]
    origin = candidate.get("candidate_origin", "expert_signal")
    order_type = candidate.get("pending_order_type") or "ORDEN PENDIENTE TBD"
    instruction = candidate.get("order_instruction") or "Usar la entrada, SL, TP y lote indicados sin modificar sus valores."
    direction = str(candidate.get("direction", ""))
    direction_icon = "🔻" if direction == "SELL" else "🔺" if direction == "BUY" else "➡️"
    origin_label = {
        "expert_signal": "Señal experta",
        "reentry": "Reentrada técnica",
        "technical_reversal": "Reversión técnica",
    }.get(str(origin), str(origin).replace("_", " ").title())
    risk = candidate.get("risk_usd")
    size = candidate.get("size") or "TBD"
    valid_until = candidate.get("valid_until")
    validity = "Confirmar vigencia"
    if valid_until:
        try:
            validity = datetime.fromisoformat(str(valid_until).replace("Z", "+00:00")).strftime("%H:%M UTC")
        except ValueError:
            validity = str(valid_until)
    risk_text = f"${float(risk):.2f}" if isinstance(risk, (int, float)) else "TBD"
    score_text = f"{float(candidate.get('score_total')):.2f}/{float(candidate.get('score_max')):.2f}" if candidate.get("score_total") is not None else "TBD"
    return (
        f"{direction_icon} <b>{rank}. {html.escape(str(candidate.get('asset', '')))} {html.escape(direction)}</b>\n"
        f"└ 🧩 {html.escape(origin_label)}\n"
        f"└ 🧾 Orden: <b>{html.escape(str(order_type))}</b>\n"
        f"└ 🎯 Entrada: <code>{html.escape(str(candidate.get('entry', '-')))}</code>\n"
        f"└ 🛑 SL: <code>{html.escape(str(candidate.get('stop_loss', '-')))}</code>\n"
        f"└ ✅ TP1: <code>{html.escape(str(tp))}</code>  |  ⚖️ R/R: <b>{rr:.2f}</b>\n"
        f"└ 💵 Riesgo: <b>{risk_text}</b>  |  📦 Tamaño: <b>{html.escape(str(size))}</b>\n"
        f"└ 📐 Calidad: <b>{score_text}</b>  |  ID: <code>{html.escape(str(candidate.get('idea_id', 'TBD')))}</code>\n"
        f"└ ⏳ Válida hasta: <b>{html.escape(validity)}</b>\n"
        f"\n⚡ <b>Ejecución</b>\n{html.escape(str(instruction))}\nUna sola entrada por ID; no reingresar tras TP o SL."
    )


def build_summary(candidates: list[dict[str, Any]], metadata: dict[str, Any], max_risk_usd: float) -> str:
    ranked, _ = rank_candidates(candidates, max_risk_usd, metadata.get("scoring_weights"), metadata.get("source_trust"))
    top = [item for item in ranked if item[2].get("signal_status") != "llegada_tarde"][:3]
    lines = [
        "📊 <b>SESIÓN DE TRADING · FBS</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🔎 <b>{metadata.get('telegram_messages_reviewed', 0)}</b> mensajes revisados",
        f"🛡 Riesgo máximo por operación: <b>${max_risk_usd:.2f}</b>",
        "",
        "🏆 <b>OPORTUNIDADES EVALUADAS</b>",
        "",
    ]
    for index, (_, _, candidate) in enumerate(top, 1):
        lines.extend([_candidate_line(index, candidate), ""])
    fallback = metadata.get("fallback_opportunities") or {}
    rejection_reasons = ", ".join(dict.fromkeys(reason_label(item.get("reason")) for item in (fallback.get("rejections") or [])[:4]))
    for index in range(len(top) + 1, 4):
        reason = rejection_reasons or "sin evidencia técnica suficiente"
        lines.extend([
            f"⏸ <b>{index}. NO TRADE</b>\n└ Esperar: {html.escape(reason)}",
            "",
        ])
    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        "⚠️ <b>ANTES DE OPERAR</b>",
        "Confirma en FBS el precio, spread, cierre de vela, contrato y margen.",
        "",
        "🤖 Análisis informativo · No se ejecutaron órdenes.",
    ])
    message = "\n".join(lines).strip()
    if len(message) > 4096:
        message = message[:4030] + "\n…\nAnálisis informativo; confirmar todo en FBS."
    return message


def publish(candidates_path: Path, metadata_path: Path, max_risk_usd: float, token: str, chat_id: str, dry_run: bool = False) -> dict[str, Any]:
    candidates = json.loads(candidates_path.read_text())
    metadata = json.loads(metadata_path.read_text())
    message = build_summary(candidates, metadata, max_risk_usd)
    if dry_run:
        return {"status": "dry_run", "chat_id": chat_id, "message": message}
    response = bot_api(token, "sendMessage", {"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": "true"})
    sent = response.get("result") or {}
    return {"status": "sent", "chat_id": chat_id, "message_id": sent.get("message_id")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure or publish the trading-session Telegram summary.")
    parser.add_argument("--discover", action="store_true", help="List private channels seen in Bot API updates.")
    parser.add_argument("--test", action="store_true", help="Send a short test message to TELEGRAM_TARGET_CHAT_ID.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--max-risk-usd", type=float, default=20.0)
    args = parser.parse_args()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_TARGET_CHAT_ID", "").strip()
    if not token:
        print(json.dumps({"status": "configuration_error", "error": "TELEGRAM_BOT_TOKEN is required"}, indent=2))
        return 2
    try:
        if args.discover:
            print(json.dumps({"channels": discover_channels(token)}, indent=2, ensure_ascii=False))
            return 0
        if args.test:
            if not chat_id:
                raise ValueError("TELEGRAM_TARGET_CHAT_ID is required")
            result = bot_api(token, "sendMessage", {"chat_id": chat_id, "text": "✅ Canal configurado para Trading Session."})
            print(json.dumps({"status": "sent", "message_id": (result.get("result") or {}).get("message_id")}, indent=2))
            return 0
        if not chat_id or not args.candidates or not args.metadata:
            raise ValueError("TELEGRAM_TARGET_CHAT_ID, --candidates and --metadata are required")
        print(json.dumps(publish(args.candidates, args.metadata, args.max_risk_usd, token, chat_id, args.dry_run), indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "delivery_failed", "error": str(exc)}, indent=2, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
