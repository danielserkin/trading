from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from web_runtime import monthly_carry


def fake_market(symbol: str) -> dict:
    start = date(2026, 8, 3)
    bars = []
    day = start
    value = 1.1 if not symbol.endswith("JPY") else 150.0
    while day <= date(2026, 9, 2):
        if day.weekday() < 5:
            bars.append({"date": day, "open": value, "high": value + 0.01, "low": value - 0.01, "close": value})
        day += timedelta(days=1)
    return {"bars": bars, "current": value, "proxy_symbol": f"{symbol}=X"}


class MonthlyCarryTests(unittest.TestCase):
    @patch.object(monthly_carry, "yahoo", side_effect=fake_market)
    def test_outside_entry_window_returns_wait_card(self, _mock_yahoo):
        result = monthly_carry.build(datetime(2026, 9, 9, 12, tzinfo=timezone.utc))
        self.assertEqual(result["cards"][0]["status"], "NO_TRADE")
        self.assertFalse(result["cards"][0]["monitorable"])

    @patch.object(monthly_carry, "rates_for")
    @patch.object(monthly_carry, "yahoo", side_effect=fake_market)
    def test_second_trading_day_builds_one_managed_card(self, _mock_yahoo, mock_rates):
        rates = {currency: 2.0 for currency in monthly_carry.RATE_SERIES}
        rates.update({"GBP": 5.0, "JPY": 0.0})
        mock_rates.return_value = (rates, {currency: "2026-07-01" for currency in rates})
        result = monthly_carry.build(datetime(2026, 9, 2, 12, tzinfo=timezone.utc))
        self.assertEqual(result["summary"]["valid_candidates"], 1)
        self.assertEqual(len(result["cards"]), 1)
        card = result["cards"][0]
        self.assertEqual(card["asset"], "GBPJPY")
        self.assertEqual(card["direction"], "BUY")
        self.assertEqual(card["management_horizon_trading_days"], 20)
        self.assertEqual(card["strategy_type"], "monthly_carry")
        self.assertTrue(card["monitorable"])


if __name__ == "__main__":
    unittest.main()
