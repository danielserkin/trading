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
    risk = abs(float(entry) - float(sl))
    reward = abs(float(tps[0]) - float(entry))
    if risk == 0:
        return None
    return reward / risk


def score(candidate: dict[str, Any], max_risk_usd: float) -> tuple[int, list[str]]:
    reasons: list[str] = []
    rr = risk_reward(candidate)
    points = 1
    source_trust = {
        "binance_market": 1,
    }.get(candidate.get("source"), 0)

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
    if risk_usd is None or float(risk_usd) <= max_risk_usd:
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

    return stars, reasons or ["candidate accepted"]


def render_report(candidates: list[dict[str, Any]], max_risk_usd: float, metadata: dict[str, Any] | None = None) -> str:
    ranked = []
    discarded = []
    for candidate in candidates:
        missing = candidate.get("missing") or []
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
            discarded.append((candidate, "stale_market_data"))
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
    top = ranked[:3]
    backup = ranked[3:5]

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
        "| Rank | Stars | Source | Provider | Asset | Direction | Entry | Current | SL | TP | R/R | Risk USD | Size | Valid Until | Evidence | Why |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(_candidate_rows(top, 1))
    lines.extend([
        "",
        "## Backup Candidates",
        "",
        "| Rank | Stars | Source | Provider | Asset | Direction | Entry | Current | SL | TP | R/R | Risk USD | Size | Valid Until | Evidence | Why |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    lines.extend(_candidate_rows(backup, 4))
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
        "| {rank} | {stars} | {source} | {provider} | {asset} | {direction} | {entry} | {current} | {sl} | {tp} | {rr} | {risk} | {size} | {valid_until} | {evidence} | {why} |".format(
                rank=start_rank + offset,
                stars="*" * stars,
                source=candidate.get("source", ""),
                provider=candidate.get("provider") or candidate.get("channel", ""),
                asset=candidate.get("asset", ""),
                direction=candidate.get("direction", ""),
                entry=candidate.get("entry", ""),
                current=candidate.get("current_price", "TBD"),
                sl=candidate.get("stop_loss", ""),
                tp=tp,
                rr=f"{rr:.2f}" if rr is not None else "TBD",
                risk=candidate.get("risk_usd") if candidate.get("risk_usd") is not None else "TBD",
                size=candidate.get("size", "TBD"),
                valid_until=candidate.get("valid_until", "TBD"),
                evidence=str(candidate.get("evidence", "")).replace("|", "/"),
                why=_why(candidate, reasons),
            )
        )
    return rows


def _why(candidate: dict[str, Any], reasons: list[str]) -> str:
    parts = []
    if candidate.get("execution_bias"):
        parts.append(str(candidate["execution_bias"]))
    if candidate.get("setup_type"):
        parts.append(str(candidate["setup_type"]))
    parts.extend(reasons[:2])
    return ", ".join(parts)


def _metadata_summary(metadata: dict[str, Any] | None) -> list[str]:
    if not metadata:
        return []
    lines = []
    if metadata.get("scanned_symbols") is not None:
        lines.append(f"- Symbols scanned: {metadata['scanned_symbols']}")
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
        f"- CoinGecko markets reviewed: {metadata.get('coingecko_markets', 'TBD')}",
        f"- Binance USDT spot symbols available: {metadata.get('binance_usdt_symbols', 'TBD')}",
        f"- Universe symbols after cross-check: {metadata.get('universe_symbols', 'TBD')}",
        f"- Symbols scanned: {metadata.get('scanned_symbols', 'TBD')}",
    ]
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
