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
        self.allowed = {"AAPL", "BTCUSD", "EURUSD", "NZDCHF", "XAUUSD", "US30", "US100", "DOGUSD"}
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

    def test_parse_compact_symbol_direction(self) -> None:
        candidate = self.parse("US30SELL 52970 TP 52930 TP 52870 SL 53100")
        self.assertEqual(candidate["asset"], "US30")
        self.assertEqual(candidate["direction"], "SELL")
        self.assertEqual(candidate["entry"], 52970)
        self.assertEqual(candidate["stop_loss"], 53100)
        self.assertEqual(candidate["take_profits"], [52930, 52870])

    def test_parse_compact_alias_direction(self) -> None:
        candidate = self.parse("GOLDSELL 4066/4068 SL 4076 TP 4060")
        self.assertEqual(candidate["asset"], "XAUUSD")
        self.assertEqual(candidate["direction"], "SELL")
        self.assertEqual(candidate["entry"], 4067)

    def test_parse_compact_direction_symbol(self) -> None:
        candidate = self.parse("BUYUS100 28400 SL 28300 TP 28600")
        self.assertEqual(candidate["asset"], "US100")
        self.assertEqual(candidate["direction"], "BUY")
        self.assertEqual(candidate["entry"], 28400)

    def test_reject_signal_after_tp_hit(self) -> None:
        candidate = self.parse("BUY XAUUSD Entry 4087 SL 4055 TP 4097")
        candidate["current_price"] = 4162
        reason = session.validate_current_market_state(candidate)
        self.assertEqual(reason, "tp_already_hit")

    def test_reject_signal_too_close_to_stop(self) -> None:
        candidate = self.parse("BUY GBPUSD Entry 1.3458 SL 1.3452 TP 1.3468")
        candidate["current_price"] = 1.3453
        reason = session.validate_current_market_state(candidate)
        self.assertEqual(reason, "too_close_to_stop")

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

    def test_dedupe_keeps_duplicate_as_auditable_rejection(self) -> None:
        first = self.parse("BUY BTCUSD 118000 SL 117000 TP 120000")
        second = self.parse("LONG BTCUSD 118000 SL 117000 TP 120000")
        unique = session.dedupe([first, second])
        self.assertEqual(len(unique), 2)
        self.assertIn("duplicate", second["missing"])
        self.assertEqual(second["discard_reason"], "duplicate_trade_idea")

    def test_forex_lot_size_uses_quote_currency_conversion(self) -> None:
        original_fetch = session.fetch_yahoo_current
        session.fetch_yahoo_current = lambda asset: 1.0 if asset == "USDCHF" else None
        try:
            candidate = self.parse("BUY NZDCHF Entry 0.5000 SL 0.4998 TP 0.5004")
            sizing = session.estimate_fbs_lot_size(candidate, 2.0)
        finally:
            session.fetch_yahoo_current = original_fetch
        self.assertIsNotNone(sizing)
        self.assertEqual(sizing["size"], "0.10 lot")
        self.assertEqual(sizing["risk_usd"], 2.0)
        self.assertEqual(sizing["tp1_profit_usd"], 4.0)

    def test_us30_minimum_lot_risks_eleven_dollars(self) -> None:
        candidate = self.parse("BUY US30 Entry 54036.6 SL 53926.6 TP 54336.6")
        sizing = session.estimate_fbs_lot_size(candidate, 20.0)
        self.assertIsNotNone(sizing)
        self.assertEqual(sizing["size"], "0.01 lot")
        self.assertEqual(sizing["risk_usd"], 11.0)

    def test_us30_does_not_round_above_risk_limit(self) -> None:
        candidate = self.parse("BUY US30 Entry 54036.6 SL 53926.6 TP 54336.6")
        sizing = session.estimate_fbs_lot_size(candidate, 20.0)
        self.assertLessEqual(sizing["risk_usd"], 20.0)

    def test_assigns_pending_order_from_entry_relation(self) -> None:
        cases = [
            ("BUY", 101, 100, "BUY STOP"),
            ("BUY", 99, 100, "BUY LIMIT"),
            ("SELL", 99, 100, "SELL STOP"),
            ("SELL", 101, 100, "SELL LIMIT"),
        ]
        for direction, entry, current, expected in cases:
            with self.subTest(expected=expected):
                candidate = {"direction": direction, "entry": entry, "current_price": current}
                session.assign_pending_order(candidate)
                self.assertEqual(candidate["pending_order_type"], expected)
                self.assertIn(expected, candidate["order_instruction"])
                self.assertIn(candidate["alternate_order_type"], candidate["order_instruction"])
                self.assertIn("sin cambiar entrada, SL, TP ni lote", candidate["order_instruction"])

    def test_minimum_lot_over_limit_is_ranked_as_risk_rejection(self) -> None:
        candidate = self.parse("BUY US30 Entry 54036.6 SL 53826.6 TP 54636.6")
        candidate.update({"market_valid": True, "signal_status": "vigente"})
        session.apply_position_sizing(candidate, 20.0)
        ranked, discarded = session.rank_candidates([candidate], 20.0)
        self.assertEqual(ranked, [])
        self.assertEqual(discarded[0][1], "risk_above_limit")


if __name__ == "__main__":
    unittest.main()
