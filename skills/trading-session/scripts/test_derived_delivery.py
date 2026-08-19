#!/usr/bin/env python3
"""Tests for fallback opportunities and Telegram summaries."""

from __future__ import annotations

import math
import os
import sys
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import derive_opportunities as derived
import publish_telegram_summary as publisher
import run_telegram_fbs_session as session


def market_rows(direction: str) -> list[dict[str, float]]:
    slope = 0.015 if direction == "BUY" else -0.015
    rows = []
    for index in range(80):
        close = 100 + slope * index + math.sin(index) * 0.12
        rows.append({"open": close - slope, "high": close + 0.18, "low": close - 0.18, "close": close, "volume": 100 + index % 5, "closed_at": 1_700_000_000 + index * 900})
    return rows


def snapshot(direction: str) -> dict:
    rows = market_rows(direction)
    return {"provider": "test", "market_symbol": "TEST", "bid": rows[-1]["close"] - 0.01, "ask": rows[-1]["close"] + 0.01, "rows": {"15m": rows, "1h": rows, "4h": rows}}


class DerivedOpportunityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc)
        self.seed = {
            "source": "telegram_signal", "expert_signal": True, "asset": "BTCUSD", "direction": "BUY",
            "timestamp": "2026-08-06T19:00:00+00:00", "channel": "expert", "channel_priority": 2,
            "message_url": "https://t.me/expert/1", "market_valid": False, "signal_status": "descartada", "missing": [],
        }

    def test_builds_reentry_in_same_direction(self) -> None:
        candidate, reason = derived.build_derived_candidate(self.seed, snapshot("BUY"), 1.6, True, self.now)
        self.assertEqual(reason, "accepted")
        self.assertEqual(candidate["candidate_origin"], "reentry")
        self.assertEqual(candidate["direction"], "BUY")
        self.assertGreaterEqual((candidate["take_profits"][0] - candidate["entry"]) / (candidate["entry"] - candidate["stop_loss"]), 1.59)

    def test_builds_clearly_labeled_reversal(self) -> None:
        candidate, reason = derived.build_derived_candidate(self.seed, snapshot("SELL"), 1.6, True, self.now)
        self.assertEqual(reason, "accepted")
        self.assertEqual(candidate["candidate_origin"], "technical_reversal")
        self.assertEqual(candidate["direction"], "SELL")

    def test_does_not_reverse_when_disabled(self) -> None:
        candidate, reason = derived.build_derived_candidate(self.seed, snapshot("SELL"), 1.6, False, self.now)
        self.assertIsNone(candidate)
        self.assertEqual(reason, "higher_timeframes_not_aligned")

    def test_summary_fills_three_slots_with_no_trade(self) -> None:
        candidate, _ = derived.build_derived_candidate(self.seed, snapshot("BUY"), 1.6, True, self.now)
        candidate.update({"risk_usd": 2.0, "size": "test size", "valid_until": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()})
        summary = publisher.build_summary([candidate], {"telegram_messages_reviewed": 12, "fallback_opportunities": {}}, 2.0)
        self.assertIn("1. BTCUSD BUY", summary)
        self.assertIn("Una sola entrada por ID", summary)
        self.assertEqual(summary.count("NO TRADE"), 2)
        self.assertLessEqual(len(summary), 4096)

    def test_preflight_blocks_missing_credentials(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            errors = session.preflight([])
        self.assertTrue(any("TELEGRAM_API_ID" in error for error in errors))

    def test_preflight_explains_missing_telethon(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_API_ID": "1", "TELEGRAM_API_HASH": "hash"}, clear=True), patch.dict(sys.modules, {"telethon": None}):
            errors = session.preflight([])
        self.assertTrue(any("requirements.txt" in error for error in errors))

    def test_bot_http_error_does_not_expose_token(self) -> None:
        secret = "123:super-secret-token"
        error = urllib.error.HTTPError(f"https://api.telegram.org/bot{secret}/sendMessage", 401, "Unauthorized", {}, None)
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "HTTP 401") as caught:
                publisher.bot_api(secret, "sendMessage", {"chat_id": "-1", "text": "test"})
        self.assertNotIn(secret, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
