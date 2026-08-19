#!/usr/bin/env python3
"""Score normalized trade candidates from JSON and render a Markdown report."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


REASON_LABELS = {
    "higher_timeframes_not_aligned": "1h y 4h no están alineados",
    "15m_opposes_higher_timeframes": "15m contradice la tendencia principal",
    "volume_confirmation_missing": "falta confirmación de volumen",
    "buy_overextended_rsi": "compra sobreextendida por RSI",
    "sell_overextended_rsi": "venta sobreextendida por RSI",
    "market_data_error": "falló el proveedor de mercado",
    "market_proxy_unavailable": "no hay proxy de mercado compatible",
    "insufficient_closed_candles": "faltan velas cerradas",
}


def reason_label(reason: Any) -> str:
    value = str(reason)
    return REASON_LABELS.get(value, value.replace("_", " "))


def risk_reward(candidate: dict[str, Any]) -> float | None:
    entry = candidate.get("entry")
    sl = candidate.get("stop_loss")
    tps = candidate.get("take_profits") or []
    direction = candidate.get("direction")
    if entry is None or sl is None or not tps or direction not in {"BUY", "SELL"}:
        return None
    entry_f = float(entry)
    sl_f = float(sl)
    tp_f = float(tps[0])
    if direction == "BUY":
        risk = entry_f - sl_f
        reward = tp_f - entry_f
    else:
        risk = sl_f - entry_f
        reward = entry_f - tp_f
    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


DEFAULT_SCORING_WEIGHTS = {
    "expert_signal": 1.2,
    "channel_priority": 1.0,
    "source_quality": 1.2,
    "freshness": 1.0,
    "risk_reward": 1.2,
    "entry_distance": 1.0,
    "spread_liquidity": 0.8,
    "signal_clarity": 1.0,
    "broker_universe": 1.0,
    "timeframe_alignment": 1.2,
    "origin_quality": 1.0,
}


def _freshness(candidate: dict[str, Any]) -> float:
    if candidate.get("signal_status") not in {"vigente", "cerca_de_entrada"}:
        return 0.0
    valid_until = candidate.get("valid_until")
    if not valid_until:
        return 0.65
    try:
        expires = datetime.fromisoformat(str(valid_until).replace("Z", "+00:00"))
        expires = expires.astimezone(timezone.utc) if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
        return 1.0 if expires > datetime.now(timezone.utc) else 0.0
    except ValueError:
        return 0.5


def _alignment(candidate: dict[str, Any]) -> float:
    analysis = candidate.get("analysis") if isinstance(candidate.get("analysis"), dict) else {}
    direction = candidate.get("direction")
    trends = [analysis.get(f"trend_{interval}") for interval in ("15m", "1h", "4h")]
    if trends[1:] == [direction, direction]:
        return 1.0 if trends[0] == direction else 0.55 if trends[0] == "NEUTRAL" else 0.0
    return 0.5 if not any(trends) else 0.0


def score(
    candidate: dict[str, Any],
    max_risk_usd: float,
    scoring_weights: dict[str, Any] | None = None,
    source_trust: dict[str, Any] | None = None,
) -> tuple[int, list[str]]:
    weights = {**DEFAULT_SCORING_WEIGHTS, **(scoring_weights or {})}
    trusts = source_trust or {"telegram_signal": 4, "telegram_derived": 3, "binance_market": 4}
    rr = risk_reward(candidate)
    analysis = candidate.get("analysis") if isinstance(candidate.get("analysis"), dict) else {}
    priority = int(candidate.get("channel_priority") or 4)
    confidence = {"high": 1.0, "medium": 0.65, "low": 0.3}.get(str(candidate.get("confidence")), 0.5)
    origin = str(candidate.get("candidate_origin") or "expert_signal")
    origin_quality = {"expert_signal": 1.0, "reentry": 0.85, "technical_reversal": 0.65}.get(origin, 0.5)
    evidence_available = any(analysis.get(key) is not None for key in ("spread", "volume_ratio_15m"))
    distance = candidate.get("entry_distance_percent")
    entry_quality = max(0.0, 1.0 - float(distance) / 1.2) if distance is not None else 0.5
    max_trust = max([float(value) for value in trusts.values()] or [1.0])
    source_key = str(candidate.get("source") or "")
    source_value = float(trusts.get(source_key, trusts.get("telegram_signal", 0))) / max_trust
    components = {
        "expert_signal": 1.0 if candidate.get("expert_signal") else 0.35,
        "channel_priority": max(0.0, min(1.0, (4 - priority) / 3)),
        "source_quality": source_value,
        "freshness": _freshness(candidate),
        "risk_reward": min(1.0, (rr or 0.0) / 2.0),
        "entry_distance": entry_quality,
        "spread_liquidity": 1.0 if evidence_available else 0.35,
        "signal_clarity": confidence,
        "broker_universe": 1.0 if candidate.get("market_valid", True) else 0.0,
        "timeframe_alignment": _alignment(candidate),
        "origin_quality": origin_quality,
    }
    weighted = {name: round(value * float(weights.get(name, 0.0)), 4) for name, value in components.items()}
    maximum = sum(max(0.0, float(weights.get(name, 0.0))) for name in components) or 1.0
    total = round(sum(weighted.values()), 4)
    ratio = total / maximum
    stars = 5 if ratio >= 0.85 else 4 if ratio >= 0.70 else 3 if ratio >= 0.55 else 2 if ratio >= 0.40 else 1
    reasons = [
        f"score {total:.2f}/{maximum:.2f}",
        "alineación completa" if components["timeframe_alignment"] == 1.0 else "15m neutral/limitado",
        f"origen {origin}",
        f"R/R {rr:.2f}" if rr is not None else "R/R no disponible",
    ]
    if not evidence_available:
        reasons.append("sin volumen/spread confirmado")
    candidate["score_total"] = total
    candidate["score_max"] = round(maximum, 4)
    candidate["score_components"] = weighted
    candidate["score_factors"] = {name: round(value, 4) for name, value in components.items()}
    return stars, reasons


def rank_candidates(
    candidates: list[dict[str, Any]],
    max_risk_usd: float,
    scoring_weights: dict[str, Any] | None = None,
    source_trust: dict[str, Any] | None = None,
) -> tuple[list[tuple[int, list[str], dict[str, Any]]], list[tuple[dict[str, Any], str]]]:
    ranked = []
    discarded = []
    for candidate in candidates:
        missing = candidate.get("missing") or []
        valid_until = candidate.get("valid_until")
        if valid_until:
            try:
                expires = datetime.fromisoformat(str(valid_until).replace("Z", "+00:00"))
                expires = expires.astimezone(timezone.utc) if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
                if expires <= datetime.now(timezone.utc):
                    candidate["signal_status"] = "vencida"
                    candidate["discard_reason"] = "expired_at_ranking"
            except ValueError:
                pass
        if candidate.get("signal_status") in {"vencida", "duplicada", "incompleta", "descartada"}:
            discarded.append((candidate, candidate.get("discard_reason") or candidate.get("signal_status")))
            continue
        if "telegram_client" in missing or "telegram_credentials" in missing or "telegram_channel" in missing:
            discarded.append((candidate, candidate.get("error") or "telegram_access_error"))
            continue
        if "unknown_fbs_symbol" in missing:
            discarded.append((candidate, "unknown_fbs_symbol"))
            continue
        if "broker_universe" in missing:
            discarded.append((candidate, "outside_fbs_universe"))
            continue
        if "market_data" in missing:
            discarded.append((candidate, "stale_market_data"))
            continue
        if "direction" in missing or not candidate.get("direction"):
            discarded.append((candidate, "parse_uncertain"))
            continue
        if "entry" in missing or candidate.get("entry") in (None, ""):
            discarded.append((candidate, "parse_uncertain"))
            continue
        if "stop_loss" in missing:
            discarded.append((candidate, "missing_sl"))
            continue
        if "take_profit" in missing:
            discarded.append((candidate, "missing_tp"))
            continue
        if candidate.get("market_valid") is False:
            discarded.append((candidate, candidate.get("discard_reason") or candidate.get("signal_status") or "market_validation_failed"))
            continue
        if candidate.get("risk_usd") is None:
            discarded.append((candidate, "risk_unavailable"))
            continue
        rr = risk_reward(candidate)
        if rr is not None and rr < 1.5:
            discarded.append((candidate, "risk_above_limit"))
            continue
        if candidate.get("risk_usd") is not None and float(candidate["risk_usd"]) > max_risk_usd:
            discarded.append((candidate, "risk_above_limit"))
            continue
        stars, reasons = score(candidate, max_risk_usd, scoring_weights, source_trust)
        ranked.append((stars, reasons, candidate))

    ranked.sort(
        key=lambda item: (
            float(item[2].get("score_total") or 0),
            item[0],
            float(item[2].get("quality_score") or 0),
        ),
        reverse=True,
    )
    return ranked, discarded


def render_report(candidates: list[dict[str, Any]], max_risk_usd: float, metadata: dict[str, Any] | None = None) -> str:
    metadata = metadata or {}
    ranked, discarded = rank_candidates(candidates, max_risk_usd, metadata.get("scoring_weights"), metadata.get("source_trust"))
    top = [item for item in ranked if item[2].get("signal_status") != "llegada_tarde"][:3]
    top_ids = {id(item[2]) for item in top}
    backup = [item for item in ranked if id(item[2]) not in top_ids][:5 - len(top)]

    lines = [
        f"# Trading Session - {date.today().isoformat()}",
        "",
        "## Summary",
        "",
        f"- Candidates reviewed: {len(candidates)}",
        f"- Valid candidates: {len(ranked)}",
        f"- Risk limit: {max_risk_usd:.2f} USD",
        *_metadata_summary(metadata),
        "",
        "## Top Candidates",
        "",
        "| Rank | Stars | Source | Provider | Asset | Direction | Entry | Current | SL | TP | R/R | Risk USD | Size | Volume Est. | Valid Until | Evidence | Why |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(_candidate_rows(top, 1))
    target = int(((metadata or {}).get("fallback_opportunities") or {}).get("target", 3))
    no_trade_slots = max(0, target - len(top))
    lines.extend(_no_trade_rows(no_trade_slots, len(top) + 1, metadata))
    lines.extend([
        "",
        "## Backup Candidates",
        "",
        "| Rank | Stars | Source | Provider | Asset | Direction | Entry | Current | SL | TP | R/R | Risk USD | Size | Volume Est. | Valid Until | Evidence | Why |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    lines.extend(_candidate_rows(backup, len(top) + 1))
    lines.extend([
        "",
        "## Discarded Signals",
        "",
        "| Source | Provider | Raw Asset | Direction | Reason |",
        "| --- | --- | --- | --- | --- |",
    ])
    for candidate, reason in discarded:
        lines.append(f"| {candidate.get('source', '')} | {candidate.get('provider') or candidate.get('channel', '')} | {candidate.get('asset', '')} | {candidate.get('direction', '')} | {reason} |")
    lines.extend([
        "",
        "## Data Used",
        "",
        *_data_used(metadata),
        "",
        "## Notes",
        "",
        "- Recommendations only. User must decide execution manually.",
    ])
    return "\n".join(lines) + "\n"


def _no_trade_rows(count: int, start_rank: int, metadata: dict[str, Any] | None) -> list[str]:
    rejections = ((metadata or {}).get("fallback_opportunities") or {}).get("rejections") or []
    reasons = ", ".join(dict.fromkeys(reason_label(item.get("reason")) for item in rejections[:4])) or "sin configuración técnica con evidencia suficiente"
    return [
        f"| {start_rank + offset} | * | system | fallback_engine | NO TRADE | WAIT | - | - | - | - | - | 0 | - | - | - | - | No operar: {reasons} |"
        for offset in range(count)
    ]


def _candidate_rows(items: list[tuple[int, list[str], dict[str, Any]]], start_rank: int) -> list[str]:
    rows = []
    for offset, (stars, reasons, candidate) in enumerate(items):
        rr = risk_reward(candidate)
        tp = (candidate.get("take_profits") or [""])[0]
        rows.append(
        "| {rank} | {stars} | {source} | {provider} | {asset} | {direction} | {entry} | {current} | {sl} | {tp} | {rr} | {risk} | {size} | {volume} | {valid_until} | {evidence} | {why} |".format(
                rank=start_rank + offset,
                stars="*" * stars,
                source=candidate.get("source", ""),
                provider=candidate.get("provider") or candidate.get("channel", ""),
                asset=candidate.get("asset", ""),
                direction=candidate.get("direction", ""),
                entry=_format_entry(candidate),
                current=_format_current(candidate),
                sl=candidate.get("stop_loss", ""),
                tp=tp,
                rr=f"{rr:.2f}" if rr is not None else "TBD",
                risk=candidate.get("risk_usd") if candidate.get("risk_usd") is not None else "TBD",
                size=candidate.get("size", "TBD"),
                volume=_format_volume_estimate(candidate),
                valid_until=candidate.get("valid_until", "TBD"),
                evidence=str(candidate.get("evidence", "")).replace("|", "/"),
                why=_why(candidate, reasons),
            )
        )
    return rows


def _format_entry(candidate: dict[str, Any]) -> str:
    entry = candidate.get("entry", "")
    direction = candidate.get("direction")
    analysis = candidate.get("analysis") if isinstance(candidate.get("analysis"), dict) else {}
    if direction == "BUY" and analysis.get("ask") is not None:
        return f"Ask {entry}"
    if direction == "SELL" and analysis.get("bid") is not None:
        return f"Bid {entry}"
    return str(entry)


def _format_current(candidate: dict[str, Any]) -> str:
    analysis = candidate.get("analysis") if isinstance(candidate.get("analysis"), dict) else {}
    bid = analysis.get("bid")
    ask = analysis.get("ask")
    spread = analysis.get("spread")
    if bid is not None and ask is not None:
        suffix = f", spr {spread}" if spread is not None else ""
        return f"Bid {bid} / Ask {ask}{suffix}"
    return str(candidate.get("current_price", "TBD"))


def _format_volume_estimate(candidate: dict[str, Any]) -> str:
    sizing = candidate.get("position_sizing")
    if isinstance(sizing, dict) and sizing.get("lot_size") is not None:
        profit = sizing.get("tp1_profit_usd")
        profit_suffix = f", TP1 ~{float(profit):.2f} USD" if profit is not None else ""
        return f"{float(sizing['lot_size']):.2f} lot{profit_suffix}"
    volume = candidate.get("volume_estimate")
    if isinstance(volume, dict):
        units = volume.get("units")
        unit = volume.get("unit")
        notional = volume.get("notional_usd")
        if units is not None and unit:
            suffix = f" (~{float(notional):.2f} USD)" if notional is not None else ""
            return f"{units} {unit}{suffix}"
    size = candidate.get("size")
    if size not in (None, "", "TBD"):
        unit = str(candidate.get("asset", "")).removesuffix("USDT").removesuffix("USD")
        return f"{size} {unit}".strip()
    return "TBD"


def _why(candidate: dict[str, Any], reasons: list[str]) -> str:
    parts = []
    if candidate.get("score_total") is not None:
        parts.append(f"score={candidate['score_total']}/{candidate.get('score_max', 'TBD')}")
    if candidate.get("pending_order_type"):
        parts.append(f"orden={candidate['pending_order_type']}")
    if candidate.get("execution_bias"):
        parts.append(str(candidate["execution_bias"]))
    if candidate.get("setup_type"):
        parts.append(str(candidate["setup_type"]))
    if candidate.get("signal_status"):
        parts.append(str(candidate["signal_status"]))
    if candidate.get("modification_note"):
        parts.append(str(candidate["modification_note"]))
    if candidate.get("candidate_origin"):
        parts.append(f"origen={candidate['candidate_origin']}")
    if candidate.get("order_instruction"):
        parts.append(str(candidate["order_instruction"]))
    if candidate.get("invalidation_condition"):
        parts.append(str(candidate["invalidation_condition"]))
    if candidate.get("seed_message_url"):
        parts.append(f"semilla={candidate['seed_message_url']}")
    if candidate.get("sizing_note"):
        parts.append(str(candidate["sizing_note"]))
    parts.extend(reasons[:2])
    return ", ".join(parts)


def _metadata_summary(metadata: dict[str, Any] | None) -> list[str]:
    if not metadata:
        return []
    lines = []
    if metadata.get("scanned_symbols") is not None:
        lines.append(f"- Symbols scanned: {metadata['scanned_symbols']}")
    if metadata.get("telegram_messages_reviewed") is not None:
        lines.append(f"- Telegram messages reviewed: {metadata['telegram_messages_reviewed']}")
    if metadata.get("broker"):
        lines.append(f"- Broker universe: {metadata['broker']}")
    fear_greed = metadata.get("fear_greed") or {}
    if fear_greed:
        lines.append(f"- Crypto regime: {fear_greed.get('regime', 'unknown')} ({fear_greed.get('classification', 'unknown')} {fear_greed.get('value', 'TBD')})")
    return lines


def _data_used(metadata: dict[str, Any] | None) -> list[str]:
    if not metadata:
        return [
            "- Source: normalized candidate JSON",
        ]
    sources = ", ".join(metadata.get("sources") or ["normalized candidate JSON"])
    lines = [
        f"- Sources: {sources}",
        f"- Broker universe: {metadata.get('broker', 'TBD')}",
        f"- Broker symbols allowed: {_broker_symbols(metadata)}",
    ]
    if metadata.get("telegram_channels") is not None:
        lines.append(f"- Telegram channels: {', '.join(metadata.get('telegram_channels') or []) or 'none'}")
        lines.append(f"- Telegram messages reviewed: {metadata.get('telegram_messages_reviewed', 'TBD')}")
    else:
        lines.extend([
            f"- CoinGecko markets reviewed: {metadata.get('coingecko_markets', 'TBD')}",
            f"- Binance USDT spot symbols available: {metadata.get('binance_usdt_symbols', 'TBD')}",
            f"- Universe symbols after cross-check: {metadata.get('universe_symbols', 'TBD')}",
            f"- Symbols scanned: {metadata.get('scanned_symbols', 'TBD')}",
        ])
    fear_greed = metadata.get("fear_greed") or {}
    if fear_greed:
        lines.append(f"- Alternative.me Fear & Greed: {fear_greed.get('classification', 'unknown')} ({fear_greed.get('value', 'TBD')})")
    return lines


def _broker_symbols(metadata: dict[str, Any]) -> str:
    symbols = metadata.get("broker_symbols")
    if isinstance(symbols, list):
        return ", ".join(symbols)
    return str(symbols or "TBD")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json", type=Path)
    parser.add_argument("--max-risk-usd", type=float, default=2.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    candidates = json.loads(args.input_json.read_text())
    if not isinstance(candidates, list):
        raise SystemExit("input_json must contain a list of candidate objects")
    report = render_report(candidates, args.max_risk_usd)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report)
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
