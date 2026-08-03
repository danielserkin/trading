#!/usr/bin/env python3
"""Score normalized trade candidates from JSON and render a Markdown report."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any


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


def score(candidate: dict[str, Any], max_risk_usd: float) -> tuple[int, list[str]]:
    reasons: list[str] = []
    rr = risk_reward(candidate)
    points = 1
    source_trust = {
        "binance_market": 1,
        "telegram_signal": 1,
    }.get(candidate.get("source"), 0)

    if candidate.get("expert_signal"):
        points += 1
        reasons.append("expert signal")
    if candidate.get("signal_status") in {"vigente", "cerca_de_entrada"}:
        points += 1
        reasons.append(str(candidate["signal_status"]))
    channel_priority = candidate.get("channel_priority")
    if channel_priority is not None and int(channel_priority) <= 2:
        points += 1
        reasons.append("priority channel")
    if candidate.get("confidence") == "high":
        points += 1
        reasons.append("clear signal")
    if source_trust > 0:
        points += source_trust
        reasons.append("verifiable source")
    if rr is not None and rr >= 1.5:
        points += 1
        reasons.append(f"R/R {rr:.2f}")
    if float(candidate.get("quality_score") or 0) >= 4:
        points += 1
        reasons.append("strong technical quality")
    risk_usd = candidate.get("risk_usd")
    if risk_usd is not None and float(risk_usd) <= max_risk_usd:
        points += 1
        reasons.append("risk within limit")
    if candidate.get("market_valid", True):
        points += 1
        reasons.append("market validated")

    stars = max(1, min(points, 5))
    if candidate.get("source") == "binance_market":
        quality_score = float(candidate.get("quality_score") or 0)
        if quality_score < 3:
            stars = min(stars, 3)
        elif quality_score < 4:
            stars = min(stars, 4)
    if candidate.get("signal_status") == "llegada_tarde":
        stars = min(stars, 3)

    return stars, reasons or ["candidate accepted"]


def render_report(candidates: list[dict[str, Any]], max_risk_usd: float, metadata: dict[str, Any] | None = None) -> str:
    ranked = []
    discarded = []
    for candidate in candidates:
        missing = candidate.get("missing") or []
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
        rr = risk_reward(candidate)
        if rr is not None and rr < 1.5:
            discarded.append((candidate, "risk_above_limit"))
            continue
        if candidate.get("risk_usd") is not None and float(candidate["risk_usd"]) > max_risk_usd:
            discarded.append((candidate, "risk_above_limit"))
            continue
        stars, reasons = score(candidate, max_risk_usd)
        ranked.append((stars, reasons, candidate))

    ranked.sort(key=lambda item: (item[0], float(item[2].get("quality_score") or 0)), reverse=True)
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
    if candidate.get("execution_bias"):
        parts.append(str(candidate["execution_bias"]))
    if candidate.get("setup_type"):
        parts.append(str(candidate["setup_type"]))
    if candidate.get("signal_status"):
        parts.append(str(candidate["signal_status"]))
    if candidate.get("modification_note"):
        parts.append(str(candidate["modification_note"]))
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
