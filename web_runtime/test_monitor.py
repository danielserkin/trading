from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from web_runtime.monitor import Candle, decision_for


NOW = datetime(2026, 8, 27, 18, 31, tzinfo=timezone.utc)


def candles(start: float, step: float, count: int, minutes: int) -> list[Candle]:
    rows = []
    opened = NOW - timedelta(minutes=minutes * count)
    for index in range(count):
        value = start + step * index
        row_open = opened + timedelta(minutes=minutes * index)
        rows.append(Candle(row_open, row_open + timedelta(minutes=minutes), value - step / 2, value + 0.0003, value - 0.0003, value, 100))
    return rows


def snapshot(step: float = 0.0001):
    return {
        "provider": "yahoo_finance_proxy",
        "proxy_symbol": "EURUSD=X",
        "m15": candles(1.1000, step, 60, 15),
        "h1": candles(1.0950, step, 60, 60),
        "h4": candles(1.0900, step, 40, 240),
    }


class DecisionTests(unittest.TestCase):
    def monitor(self, **updates):
        value = {
            "direction": "BUY", "entry": 1.1000, "stop_loss": 1.0950,
            "take_profit": 1.1150, "activated_at": (NOW - timedelta(hours=2)).isoformat(),
        }
        value.update(updates)
        return value

    def test_stop_cross_never_widens_risk(self):
        snap = snapshot(-0.00015)
        result = decision_for(self.monitor(), snap, NOW)
        self.assertEqual(result["action"], "CERRAR_TODO")

    def test_move_sl_only_improves_buy_stop(self):
        snap = snapshot(0.00012)
        result = decision_for(self.monitor(take_profit=1.1300), snap, NOW)
        self.assertEqual(result["action"], "MOVER_SL")
        self.assertGreaterEqual(result["new_sl"], 1.1000)
        self.assertLess(result["new_sl"], result["current_price"])

    def test_hold_has_no_level_mutation(self):
        snap = snapshot(0.00002)
        result = decision_for(self.monitor(), snap, NOW)
        self.assertEqual(result["action"], "MANTENER")
        self.assertNotIn("new_sl", result)
        self.assertNotIn("new_tp", result)

    def test_entry_validity_does_not_close_an_activated_trade(self):
        snap = snapshot(0.00002)
        result = decision_for(self.monitor(valid_until=(NOW + timedelta(minutes=20)).isoformat()), snap, NOW)
        self.assertEqual(result["action"], "MANTENER")

    def test_explicit_management_horizon_closes_intraday_trade(self):
        snap = snapshot(0.00002)
        result = decision_for(
            self.monitor(
                activated_at=(NOW - timedelta(hours=8)).isoformat(),
                valid_until=(NOW - timedelta(hours=7)).isoformat(),
                management_horizon_hours=8,
            ),
            snap,
            NOW,
        )
        self.assertEqual(result["action"], "CERRAR_TODO")
        self.assertTrue(any("Horizonte" in reason for reason in result["reasons"]))

    def test_legacy_monitor_without_explicit_horizon_is_not_expired(self):
        snap = snapshot(0.00002)
        result = decision_for(
            self.monitor(
                activated_at=(NOW - timedelta(hours=12)).isoformat(),
                valid_until=(NOW - timedelta(hours=11)).isoformat(),
            ),
            snap,
            NOW,
        )
        self.assertEqual(result["action"], "MANTENER")
        self.assertIsNone(result["management_deadline"])

    def test_monthly_carry_ignores_intraday_deterioration(self):
        snap = snapshot(-0.00005)
        result = decision_for(
            self.monitor(strategy_type="monthly_carry", management_horizon_trading_days=20),
            snap,
            NOW,
        )
        self.assertEqual(result["action"], "MANTENER")

    def test_monthly_carry_closes_after_twenty_trading_days(self):
        snap = snapshot(0.00002)
        result = decision_for(
            self.monitor(
                strategy_type="monthly_carry",
                activated_at="2026-07-30T18:31:00+00:00",
                management_horizon_trading_days=20,
            ),
            snap,
            NOW,
        )
        self.assertEqual(result["action"], "CERRAR_TODO")
        self.assertIn("20 días hábiles", " ".join(result["reasons"]))


if __name__ == "__main__":
    unittest.main()
