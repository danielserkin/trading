#!/usr/bin/env python3
"""Unit tests for Telegram/FBS signal parsing."""

from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_telegram_fbs_session as session


class TelegramFbsParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.allowed = {"AAPL", "BTCUSD", "EURUSD", "XAUUSD", "US100", "DOGUSD"}
        self.aliases = dict(session.SYMBOL_ALIASES)

    def parse(self, text: str) -> dict:
        return session.parse_signal(
            {
                "channel": "test",
                "handle": "@test",
                "priority": 2,
                "text": text,
                "timestamp": "2026-07-30T12:00:00+00:00",
                "message_id": 1,
                "message_url": "https://t.me/test/1",
            },
            self.allowed,
            self.aliases,
        )

    def test_parse_crypto_signal_with_labels(self) -> None:
        candidate = self.parse("BUY BTCUSD entry 118000 - 118500 SL 116900 TP1 120500 TP2 122000")
        self.assertEqual(candidate["asset"], "BTCUSD")
        self.assertEqual(candidate["direction"], "BUY")
        self.assertEqual(candidate["entry"], 118250)
        self.assertEqual(candidate["stop_loss"], 116900)
        self.assertEqual(candidate["take_profits"], [120500, 122000])

    def test_parse_forex_signal_without_entry_label(self) -> None:
        candidate = self.parse("EURUSD BUY 1.0860 SL 1.0830 TP 1.0920")
        self.assertEqual(candidate["asset"], "EURUSD")
        self.assertEqual(candidate["direction"], "BUY")
        self.assertEqual(candidate["entry"], 1.086)
        self.assertEqual(candidate["stop_loss"], 1.083)
        self.assertEqual(candidate["take_profits"], [1.092])

    def test_alias_maps_gold(self) -> None:
        candidate = self.parse("SELL GOLD 2415 SL 2428 TP 2390")
        self.assertEqual(candidate["asset"], "XAUUSD")
        self.assertEqual(candidate["direction"], "SELL")

    def test_parse_dash_numbered_take_profit(self) -> None:
        candidate = self.parse("Xau/Usd Gold Buy Now Entry Zone 4087-4082 Tp-1 4097 Tp-2 4104 SL-4055")
        self.assertEqual(candidate["asset"], "XAUUSD")
        self.assertEqual(candidate["direction"], "BUY")
        self.assertEqual(candidate["entry"], 4084.5)
        self.assertEqual(candidate["stop_loss"], 4055)
        self.assertEqual(candidate["take_profits"], [4097, 4104])

    def test_reject_signal_after_tp_hit(self) -> None:
        candidate = self.parse("BUY XAUUSD Entry 4087 SL 4055 TP 4097")
        candidate["current_price"] = 4162
        reason = session.validate_current_market_state(candidate)
        self.assertEqual(reason, "tp_already_hit")

    def test_parse_confirmed_stock_cashtag(self) -> None:
        candidate = self.parse("BUY #AAPL Entry 210 SL 204 TP 222")
        self.assertEqual(candidate["asset"], "AAPL")
        self.assertEqual(candidate["direction"], "BUY")

    def test_parse_plausible_unconfirmed_stock_cashtag(self) -> None:
        candidate = session.parse_signal(
            {
                "channel": "test",
                "handle": "@test",
                "priority": 2,
                "text": "SELL #XYZ Entry 30 SL 33 TP 25",
                "timestamp": "2026-07-30T12:00:00+00:00",
                "message_id": 2,
                "message_url": "https://t.me/test/2",
            },
            self.allowed,
            self.aliases,
        )
        self.assertEqual(candidate["asset"], "XYZ")
        self.assertEqual(candidate["symbol_status"], "plausible_unconfirmed")
        self.assertIn("unknown_fbs_symbol", candidate["missing"])

    def test_short_stock_ticker_requires_cashtag(self) -> None:
        candidate = session.parse_signal(
            {
                "channel": "test",
                "handle": "@test",
                "priority": 2,
                "text": "Esta noche zoom a las 22:00 pm hora Bolivia atentos al link",
                "timestamp": "2026-07-30T12:00:00+00:00",
                "message_id": 3,
                "message_url": "https://t.me/test/3",
            },
            {"MA", "V", "F"},
            self.aliases,
        )
        self.assertIsNone(candidate["asset"])

    def test_dedupe_keeps_first_signal(self) -> None:
        first = self.parse("BUY BTCUSD 118000 SL 117000 TP 120000")
        second = self.parse("LONG BTCUSD 118000 SL 117000 TP 120000")
        unique = session.dedupe([first, second])
        self.assertEqual(len(unique), 1)
        self.assertIn("duplicate", second["missing"])


if __name__ == "__main__":
    unittest.main()
