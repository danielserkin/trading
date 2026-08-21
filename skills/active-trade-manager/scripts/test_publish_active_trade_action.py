import unittest

from publish_active_trade_action import build_message, validate_payload


def sample(**updates):
    position = {
        "asset": "GBPCAD",
        "ticket": "1982460641",
        "direction": "BUY",
        "action": "CERRAR_TODO",
        "urgency": "AHORA",
        "instruction": "Cerrar 0.25 lotes a mercado cerca de 1.87864.",
        "reasons": ["Cierre semanal inminente"],
        "confidence": "alta",
        "volume": 0.25,
        "entry": 1.87676,
        "current_price": 1.87864,
        "current_profit_usd": 30.69,
        "old_sl": 1.87567,
        "old_tp": 1.87903,
    }
    position.update(updates)
    return {"reviewed_at": "2026-08-21T20:53:34Z", "positions": [position]}


class PublisherTests(unittest.TestCase):
    def test_example_renders(self):
        message = build_message(sample())
        self.assertIn("CERRAR TODO", message)
        self.assertIn("$30.69", message)
        self.assertIn("1982460641", message)

    def test_buy_sl_cannot_be_widened(self):
        with self.assertRaisesRegex(ValueError, "must not widen risk"):
            validate_payload(sample(action="MOVER_SL", new_sl=1.87500))

    def test_sell_sl_can_only_move_down_and_stay_above_price(self):
        validate_payload(sample(direction="SELL", action="MOVER_SL", old_sl=1.88100, current_price=1.87800, new_sl=1.87900))

    def test_tp_cannot_be_extended(self):
        with self.assertRaisesRegex(ValueError, "must be closer"):
            validate_payload(sample(action="AJUSTAR_TP", new_tp=1.88000))

    def test_partial_volumes_must_balance(self):
        with self.assertRaisesRegex(ValueError, "must equal volume"):
            validate_payload(sample(action="CIERRE_PARCIAL", close_volume=0.10, remaining_volume=0.10))

    def test_valid_partial_close(self):
        message = build_message(sample(action="CIERRE_PARCIAL", close_volume=0.15, remaining_volume=0.10, new_sl=1.87775))
        self.assertIn("Cerrar <b>0.15</b>", message)
        self.assertIn("1.87775", message)


if __name__ == "__main__":
    unittest.main()
