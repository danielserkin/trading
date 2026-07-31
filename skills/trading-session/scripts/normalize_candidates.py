#!/usr/bin/env python3
"""Normalize source-specific candidate JSON into the common trading schema."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COMMON_KEYS = {
    "source",
    "provider",
    "asset",
    "direction",
    "entry",
    "stop_loss",
    "take_profits",
    "timestamp",
    "evidence",
    "confidence",
    "current_price",
    "risk_usd",
    "market_valid",
    "valid_until",
    "size",
    "setup_type",
    "execution_bias",
    "regime",
    "source_context",
    "liquidity_rank",
    "broker",
    "broker_symbol",
    "market_symbol",
    "channel",
    "message_id",
    "message_url",
    "raw_text",
    "image_evidence",
    "parsed_by",
    "freshness_minutes",
    "signal_status",
    "expert_signal",
    "modification_note",
    "channel_priority",
    "entry_distance_percent",
}


def normalize(item: dict[str, Any], default_source: str) -> dict[str, Any]:
    source = item.get("source") or default_source
    normalized = {key: item.get(key) for key in COMMON_KEYS if key in item}
    normalized["source"] = source
    normalized["provider"] = item.get("provider") or item.get("channel") or item.get("author") or source
    normalized["asset"] = item.get("asset") or item.get("symbol")
    normalized["direction"] = _normalize_direction(item.get("direction") or item.get("side"))
    normalized["entry"] = _first_number(item.get("entry") or item.get("entry_price") or item.get("price"))
    normalized["stop_loss"] = _first_number(item.get("stop_loss") or item.get("sl"))
    normalized["take_profits"] = _tp_list(item.get("take_profits") or item.get("tp") or item.get("target"))
    normalized["timestamp"] = item.get("timestamp") or item.get("date") or datetime.now(timezone.utc).isoformat()
    normalized["evidence"] = item.get("evidence") or item.get("notes") or _default_evidence(item)
    normalized["confidence"] = item.get("confidence") or _default_confidence(source)
    normalized["missing"] = _missing_fields(normalized)
    return normalized


def _normalize_direction(value: Any) -> str | None:
    if value is None:
        return None
    direction = str(value).upper()
    if direction in {"LONG", "BUY"}:
        return "BUY"
    if direction in {"SHORT", "SELL"}:
        return "SELL"
    return None


def _first_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, list):
        value = value[0] if value else None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tp_list(value: Any) -> list[float]:
    if value in (None, ""):
        return []
    values = value if isinstance(value, list) else [value]
    parsed = []
    for item in values:
        try:
            parsed.append(float(item))
        except (TypeError, ValueError):
            continue
    return parsed


def _default_confidence(source: str) -> str:
    if source == "binance_market":
        return "medium"
    return "medium"


def _default_evidence(item: dict[str, Any]) -> str:
    stats = []
    for key in ("weeks", "trades", "drawdown_percent", "profit_factor", "scanner_condition"):
        if item.get(key) not in (None, ""):
            stats.append(f"{key}={item[key]}")
    return ", ".join(stats) if stats else "source provided structured candidate"


def _missing_fields(item: dict[str, Any]) -> list[str]:
    missing = []
    for field in ("asset", "direction", "entry", "stop_loss"):
        if item.get(field) in (None, ""):
            missing.append(field)
    if not item.get("take_profits"):
        missing.append("take_profit")
    return missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json", type=Path)
    parser.add_argument("--source", default="binance_market")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    data = json.loads(args.input_json.read_text())
    items = data if isinstance(data, list) else [data]
    normalized = [normalize(item, args.source) for item in items]
    payload = json.dumps(normalized, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
