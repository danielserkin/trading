#!/usr/bin/env python3
"""Unit tests for Telegram/FBS signal parsing."""

from __future__ import annotations

import unittest
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_telegram_fbs_session as session
import score_candidates as scoring


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

    def test_parse_take_shorthand_with_dash(self) -> None:
        candidate = self.parse(
            "#EURUSD: Long Trade Explained\n"
            "Buy EURUSD\nEntry - 1.1662\nStop - 1.1654\nTake - 1.1677\nOur Risk - 1%"
        )
        self.assertEqual(candidate["entry"], 1.1662)
        self.assertEqual(candidate["stop_loss"], 1.1654)
        self.assertEqual(candidate["take_profits"], [1.1677])

    def test_bare_take_without_separator_is_not_a_target(self) -> None:
        candidate = self.parse("BUY EURUSD Entry 1.1000 SL 1.0950 Please take 1% risk")
        self.assertEqual(candidate["take_profits"], [])

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
        self.assertEqual(first["idea_id"], second["idea_id"])

    def test_published_idea_is_rejected_across_runs(self) -> None:
        candidate = self.parse("BUY BTCUSD 118000 SL 117000 TP 120000")
        candidate.update({"market_valid": True, "signal_status": "vigente"})
        session.dedupe([candidate])
        with tempfile.TemporaryDirectory() as directory:
            ledger_path = Path(directory) / "idea-ledger.json"
            session.record_published_ideas(ledger_path, [candidate])
            published = set(session.load_idea_ledger(ledger_path)["published_ideas"])
            repeated = self.parse("BUY BTCUSD 118000 SL 117000 TP 120000")
            session.dedupe([repeated], published)
        self.assertEqual(repeated["discard_reason"], "idea_already_published")
        self.assertEqual(repeated["signal_status"], "duplicada")

    def test_expired_candidate_is_rejected_at_ranking(self) -> None:
        candidate = self.parse("BUY BTCUSD 118000 SL 117000 TP 120000")
        candidate.update({
            "market_valid": True, "signal_status": "vigente", "risk_usd": 20.0,
            "valid_until": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        })
        ranked, discarded = scoring.rank_candidates([candidate], 20.0)
        self.assertEqual(ranked, [])
        self.assertEqual(discarded[0][1], "expired_at_ranking")

    def test_channel_window_overrides_global_signal_window(self) -> None:
        candidate = self.parse("BUY BTCUSD 118000 SL 117000 TP 120000")
        candidate.update({
            "timestamp": (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat(),
            "max_age_hours": 6,
        })
        original_validator = session.validate_crypto_proxy
        session.validate_crypto_proxy = lambda item, params: item.update({"current_price": 118000.0})
        try:
            validated = session.validate_candidate(candidate, {"signal_window_hours": 24, "min_rr": 1.6, "max_risk_usd": 20}, {"crypto_cfd": ["BTCUSD"]}, {})
        finally:
            session.validate_crypto_proxy = original_validator
        self.assertEqual(validated["signal_status"], "vencida")
        self.assertIn("freshness", validated["missing"])

    def test_de30_uses_available_yahoo_index_proxy(self) -> None:
        self.assertEqual(session.YAHOO_PROXY_SYMBOLS["DE30"], "^GDAXI")

    def test_configured_weight_changes_score_and_ranking(self) -> None:
        base = {
            "asset": "EURUSD", "direction": "BUY", "entry": 1.1, "stop_loss": 1.09,
            "take_profits": [1.12], "risk_usd": 20.0, "market_valid": True,
            "signal_status": "vigente", "confidence": "medium", "channel_priority": 2,
            "source": "telegram_derived", "candidate_origin": "technical_reversal",
            "analysis": {"trend_15m": "NEUTRAL", "trend_1h": "BUY", "trend_4h": "BUY"},
        }
        aligned = dict(base, asset="GBPUSD", analysis={"trend_15m": "BUY", "trend_1h": "BUY", "trend_4h": "BUY"})
        weights = {name: 0.0 for name in scoring.DEFAULT_SCORING_WEIGHTS}
        weights["timeframe_alignment"] = 5.0
        ranked, _ = scoring.rank_candidates([base, aligned], 20.0, weights, {"telegram_derived": 3})
        self.assertEqual(ranked[0][2]["asset"], "GBPUSD")
        self.assertGreater(aligned["score_total"], base["score_total"])
        self.assertIn("timeframe_alignment", aligned["score_components"])

    def test_primary_selection_uses_three_distinct_assets(self) -> None:
        def candidate(asset: str, score_hint: float) -> dict:
            return {
                "asset": asset, "direction": "BUY", "entry": 100.0, "stop_loss": 99.0,
                "take_profits": [101.7], "risk_usd": 20.0, "market_valid": True,
                "signal_status": "vigente", "confidence": "high", "channel_priority": 2,
                "source": "technical_market_scan", "candidate_origin": "market_scan",
                "quality_score": score_hint,
                "analysis": {"trend_15m": "BUY", "trend_1h": "BUY", "trend_4h": "BUY", "volume_ratio_15m": 1.0},
            }
        ranked, _ = scoring.rank_candidates([
            candidate("EURUSD", 5.0), candidate("EURUSD", 4.9), candidate("GBPUSD", 4.8), candidate("XAUUSD", 4.7)
        ], 20.0)
        selected = scoring.select_distinct_candidates(ranked, 3)
        self.assertEqual(len(selected), 3)
        self.assertEqual(len({item[2]["asset"] for item in selected}), 3)

    def test_selection_limits_same_direction_usd_exposure(self) -> None:
        def item(asset: str, direction: str, score: float) -> tuple:
            candidate = {"asset": asset, "direction": direction, "score_total": score}
            return (4, [], candidate)

        ranked = [
            item("USDJPY", "BUY", 10),
            item("USDCHF", "BUY", 9),
            item("EURUSD", "SELL", 8),
            item("GBPUSD", "BUY", 7),
        ]
        selected = scoring.select_distinct_candidates(ranked, 3, max_same_usd_bias=2)
        self.assertEqual([row[2]["asset"] for row in selected], ["USDJPY", "USDCHF", "GBPUSD"])
        self.assertEqual(scoring.usd_bias(selected[0][2]), "LONG_USD")
        self.assertEqual(scoring.usd_bias(selected[2][2]), "SHORT_USD")

    def test_tiered_risk_scales_three_high_quality_trades_to_portfolio_cap(self) -> None:
        def candidate(asset: str) -> dict:
            return {
                "asset": asset, "direction": "BUY", "entry": 1.1000, "stop_loss": 1.0990,
                "take_profits": [1.1020], "risk_usd": 20.0, "market_valid": True,
                "signal_status": "vigente", "confidence": "high", "channel_priority": 1,
                "source": "telegram_signal", "candidate_origin": "expert_signal", "expert_signal": True,
                "entry_distance_percent": 0.0,
                "analysis": {"trend_15m": "BUY", "trend_1h": "BUY", "trend_4h": "BUY", "spread": 0.0001},
            }

        candidates = [candidate(asset) for asset in ("EURUSD", "GBPUSD", "AUDUSD")]
        params = {
            "max_risk_usd": 20,
            "primary_count": 3,
            "risk_policy": {
                "enabled": True, "minimum_actionable_stars": 3,
                "risk_by_stars_usd": {5: 10, 4: 8, 3: 4},
                "max_primary_risk_usd": 25, "max_same_usd_bias": 3,
            },
        }
        metadata = {}
        primary = session.apply_tiered_risk_policy(candidates, params, metadata)
        self.assertEqual(len(primary), 3)
        self.assertTrue(all(row[0] == 5 for row in primary))
        self.assertLessEqual(sum(row[2]["risk_usd"] for row in primary), 25)
        self.assertLess(metadata["risk_policy"]["portfolio_scale"], 1)
        self.assertTrue(all("ajustado por cartera" in row[2]["risk_policy_note"] for row in primary))

    def test_symbol_multiplier_reduces_usdjpy_without_excluding_it(self) -> None:
        candidate = {
            "asset": "USDJPY", "direction": "BUY", "entry": 160.0, "stop_loss": 159.9,
            "take_profits": [160.2], "risk_usd": 20.0, "market_valid": True,
            "signal_status": "vigente", "confidence": "high", "channel_priority": 1,
            "source": "telegram_signal", "candidate_origin": "expert_signal", "expert_signal": True,
            "entry_distance_percent": 0.0,
            "analysis": {"trend_15m": "BUY", "trend_1h": "BUY", "trend_4h": "BUY", "spread": 0.01},
        }
        params = {
            "max_risk_usd": 20, "primary_count": 3,
            "risk_policy": {
                "enabled": True, "minimum_actionable_stars": 3,
                "risk_by_stars_usd": {5: 10, 4: 8, 3: 4},
                "max_primary_risk_usd": 25, "max_same_usd_bias": 2,
                "symbol_multipliers": {"USDJPY": 0.75},
            },
        }
        original_fetch = session.fetch_yahoo_current
        session.fetch_yahoo_current = lambda asset: 160.0 if asset == "USDJPY" else None
        try:
            primary = session.apply_tiered_risk_policy([candidate], params, {})
        finally:
            session.fetch_yahoo_current = original_fetch
        self.assertEqual(len(primary), 1)
        self.assertEqual(candidate["risk_multiplier"], 0.75)
        self.assertLessEqual(candidate["risk_usd"], 7.50)
        self.assertGreater(candidate["risk_usd"], 0)

    def test_three_star_market_scan_remains_actionable_at_four_dollars(self) -> None:
        candidate = {
            "asset": "EURUSD", "direction": "BUY", "entry": 1.1000, "stop_loss": 1.0990,
            "take_profits": [1.1016], "risk_usd": 20.0, "market_valid": True,
            "signal_status": "vigente", "confidence": "medium", "channel_priority": 3,
            "source": "technical_market_scan", "candidate_origin": "market_scan", "expert_signal": False,
            "analysis": {"trend_15m": "NEUTRAL", "trend_1h": "BUY", "trend_4h": "BUY"},
        }
        params = {
            "max_risk_usd": 20, "primary_count": 3,
            "risk_policy": {
                "enabled": True, "minimum_actionable_stars": 3,
                "risk_by_stars_usd": {5: 10, 4: 8, 3: 4},
                "max_primary_risk_usd": 25, "max_same_usd_bias": 2,
            },
        }
        primary = session.apply_tiered_risk_policy([candidate], params, {})
        self.assertEqual(candidate["stars"], 3)
        self.assertEqual(len(primary), 1)
        self.assertLessEqual(candidate["risk_usd"], 4)
        self.assertGreater(candidate["risk_usd"], 0)

    def test_market_scan_asset_cooldown_keeps_expert_signal_available(self) -> None:
        now = datetime.now(timezone.utc)
        ledger = {"published_ideas": {"old": {"asset": "EURUSD", "published_at": now.isoformat()}}}
        scan = {"asset": "EURUSD", "candidate_origin": "market_scan", "signal_status": "vigente", "market_valid": True}
        expert = {"asset": "EURUSD", "candidate_origin": "expert_signal", "signal_status": "vigente", "market_valid": True}
        session.apply_market_scan_asset_cooldown([scan, expert], ledger, 24, now)
        self.assertEqual(scan["discard_reason"], "market_scan_asset_cooldown")
        self.assertTrue(expert["market_valid"])

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
