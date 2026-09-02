#!/usr/bin/env python3
"""Convert the current trading-session artifacts into a stable web payload."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SESSION_SCRIPTS = ROOT / "skills" / "trading-session" / "scripts"
sys.path.insert(0, str(SESSION_SCRIPTS))

from score_candidates import rank_candidates, risk_reward, select_distinct_candidates, selection_policy  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first(values: Any) -> Any:
    return values[0] if isinstance(values, list) and values else None


def _trade_id(candidate: dict[str, Any], run_id: str) -> str:
    idea_id = str(candidate.get("idea_id") or "").strip()
    if idea_id:
        return idea_id
    raw = "|".join(
        str(candidate.get(key) or "")
        for key in ("asset", "direction", "entry", "stop_loss", "valid_until")
    )
    return f"{run_id}-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


def card_from_candidate(
    candidate: dict[str, Any], stars: int, reasons: list[str], rank: int, run_id: str
) -> dict[str, Any]:
    analysis = candidate.get("analysis") if isinstance(candidate.get("analysis"), dict) else {}
    entry = candidate.get("entry")
    stop_loss = candidate.get("stop_loss")
    take_profit = _first(candidate.get("take_profits"))
    direction = str(candidate.get("direction") or "").upper()
    return {
        "id": _trade_id(candidate, run_id),
        "rank": rank,
        "stars": stars,
        "score": candidate.get("score_total"),
        "score_max": candidate.get("score_max"),
        "asset": candidate.get("asset"),
        "direction": direction,
        "order_type": candidate.get("pending_order_type") or "TBD",
        "entry": entry,
        "current_price": candidate.get("current_price"),
        "bid": candidate.get("current_bid"),
        "ask": candidate.get("current_ask"),
        "spread": candidate.get("spread"),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "take_profits": candidate.get("take_profits") or [],
        "risk_reward": risk_reward(candidate),
        "risk_usd": candidate.get("risk_usd"),
        "size": candidate.get("size") or "TBD",
        "valid_until": candidate.get("valid_until"),
        "source": candidate.get("source"),
        "provider": candidate.get("provider"),
        "origin": candidate.get("candidate_origin"),
        "setup_family": candidate.get("setup_family") or analysis.get("setup_family"),
        "proxy_symbol": analysis.get("proxy_symbol") or candidate.get("market_symbol"),
        "market_proxy": analysis.get("market_proxy") or candidate.get("provider"),
        "instruction": candidate.get("order_instruction"),
        "evidence": candidate.get("evidence"),
        "why": candidate.get("why"),
        "reasons": reasons,
        "monitorable": bool(
            direction in {"BUY", "SELL"}
            and isinstance(entry, (int, float))
            and isinstance(stop_loss, (int, float))
            and isinstance(take_profit, (int, float))
        ),
    }


def no_trade_card(rank: int, run_id: str, reasons: list[str]) -> dict[str, Any]:
    return {
        "id": f"{run_id}-no-trade-{rank}",
        "rank": rank,
        "status": "NO_TRADE",
        "asset": "NO TRADE",
        "direction": "WAIT",
        "stars": 0,
        "reasons": reasons or ["Evidencia técnica insuficiente"],
        "monitorable": False,
    }


def export_session(session_dir: Path) -> dict[str, Any]:
    candidates = json.loads((session_dir / "telegram-fbs-candidates.json").read_text())
    metadata = json.loads((session_dir / "telegram-fbs-metadata.json").read_text())
    delivery_path = session_dir / "telegram-delivery.json"
    delivery = json.loads(delivery_path.read_text()) if delivery_path.exists() else {"status": "unknown"}
    params_path = ROOT / "config" / "session-params.yaml"
    max_risk = 20.0
    for line in params_path.read_text().splitlines():
        if line.strip().startswith("max_risk_usd:"):
            max_risk = float(line.split(":", 1)[1].strip())
            break

    ranked, discarded = rank_candidates(
        candidates,
        max_risk,
        metadata.get("scoring_weights"),
        metadata.get("source_trust"),
    )
    minimum_stars, max_same_usd_bias = selection_policy(metadata)
    primary = select_distinct_candidates(
        ranked, 3, minimum_stars=minimum_stars, max_same_usd_bias=max_same_usd_bias
    )
    primary_ids = {id(item[2]) for item in primary}
    backups = select_distinct_candidates(
        ranked,
        2,
        excluded_ids=primary_ids,
        minimum_stars=minimum_stars,
        max_same_usd_bias=max_same_usd_bias,
    )
    run_id = str(metadata.get("run_id") or session_dir.name)
    cards = [
        card_from_candidate(candidate, stars, reasons, index, run_id)
        for index, (stars, reasons, candidate) in enumerate(primary, 1)
    ]
    rejection_reasons = [str(item[1]) for item in discarded[:4]]
    while len(cards) < 3:
        cards.append(no_trade_card(len(cards) + 1, run_id, rejection_reasons))

    return {
        "schema_version": 1,
        "run_id": run_id,
        "date": session_dir.name,
        "generated_at": utc_now(),
        "status": "completed",
        "summary": {
            "candidates_reviewed": metadata.get("candidate_count", len(candidates)),
            "valid_candidates": len(ranked),
            "messages_reviewed": metadata.get("telegram_messages_reviewed", 0),
            "symbols_scanned": metadata.get("scanned_symbols", 0),
            "max_risk_usd": max_risk,
            "max_primary_risk_usd": (metadata.get("risk_policy") or {}).get("max_primary_risk_usd"),
            "selected_primary_risk_usd": (metadata.get("risk_policy") or {}).get("selected_primary_risk_usd"),
        },
        "cards": cards,
        "backups": [
            card_from_candidate(candidate, stars, reasons, index + 4, run_id)
            for index, (stars, reasons, candidate) in enumerate(backups)
        ],
        "telegram": {key: value for key, value in delivery.items() if key != "chat_id"},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = export_session(args.session_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "exported", "output": str(args.output), "cards": len(payload["cards"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
