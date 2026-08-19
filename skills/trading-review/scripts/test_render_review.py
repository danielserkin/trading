#!/usr/bin/env python3

import unittest

from render_review import outcome_metrics


class ReviewMetricsTest(unittest.TestCase):
    def test_screenshot_baseline(self) -> None:
        pnl = [-19.80, -19.76, 29.09, -18.21, -19.24, 30.96, -19.77, 31.36, -18.95, -18.72, 36.00, -20.00]
        outcomes = [{"outcome": "win" if value > 0 else "loss", "pnl_usd": value} for value in pnl]
        metrics = outcome_metrics(outcomes)
        self.assertEqual(metrics["wins"], 4)
        self.assertEqual(metrics["losses"], 8)
        self.assertAlmostEqual(metrics["net_pnl"], -27.04, places=2)
        self.assertAlmostEqual(metrics["win_rate"], 1 / 3)
        self.assertAlmostEqual(metrics["profit_factor"], 0.8249271609)
        self.assertAlmostEqual(metrics["breakeven_win_rate"], 0.3773792362)


if __name__ == "__main__":
    unittest.main()
