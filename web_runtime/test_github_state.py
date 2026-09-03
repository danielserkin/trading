#!/usr/bin/env python3
"""Tests for bounded dashboard runtime state."""

from __future__ import annotations

import unittest

from github_state import MAX_MONITOR_HISTORY, compact_state


class CompactStateTest(unittest.TestCase):
    def test_bounds_monitor_history_and_events(self) -> None:
        state = {
            "monitors": {"trade": {"history": [{"index": index} for index in range(40)]}},
            "events": [{"index": index} for index in range(180)],
        }

        compact_state(state)

        self.assertEqual(len(state["monitors"]["trade"]["history"]), MAX_MONITOR_HISTORY)
        self.assertEqual(state["monitors"]["trade"]["history"][0]["index"], 16)
        self.assertEqual(len(state["events"]), 150)


if __name__ == "__main__":
    unittest.main()
