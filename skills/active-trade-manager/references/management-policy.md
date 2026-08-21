# Active Trade Management Policy

## Decision criteria

Use the original thesis and timeframe as the baseline, then evaluate what changed.

- `MANTENER`: thesis and structure remain intact, adequate time remains, and current protection is proportionate.
- `MOVER_SL`: the trade has made meaningful progress and a confirmed swing permits locking profit without placing the stop inside ordinary noise. Place it beyond that swing with a spread/volatility buffer; never choose break-even mechanically.
- `AJUSTAR_TP`: new resistance/support or reduced remaining time makes the original target unlikely. Move it closer only, never farther to chase price.
- `CIERRE_PARCIAL`: the position is meaningfully profitable, reversal risk exists, and enough room remains for a protected runner. Close an executable 40–60% by default, rounded to the verified broker lot step, and state the remaining volume and its SL/TP.
- `CERRAR_TODO`: the thesis is invalid, momentum failed after substantial progress, remaining reward is poor relative to giveback risk, validity expired, important news/rollover is imminent, or an intraday trade is approaching the weekend.
- `EVIDENCIA_INSUFICIENTE`: required fields or fresh prices are missing. Say exactly which screenshot or field is needed.

For M1–M30 positions, time without renewed progress materially weakens the setup. Close profitable intraday FX positions within 90 minutes of the expected weekly close unless the original setup was explicitly swing-oriented and current higher-timeframe evidence still supports carrying gap risk. A stop does not guarantee protection through a weekend gap.

Do not optimize the label `win` at the expense of expectancy. Compare the dollars/pips still available to the dollars/pips that can be given back. When at least 75% of the original path to TP has been consumed, explicitly assess profit protection, but do not apply an automatic trailing level without structure.

## Calculations

For BUY positions:

- progress = `(current_bid - entry) / (tp - entry)`
- current R = `(current_bid - entry) / (entry - original_sl)`

For SELL positions:

- progress = `(entry - current_ask) / (entry - tp)`
- current R = `(entry - current_ask) / (original_sl - entry)`

Label visually estimated MFE or swing levels as approximate. Account for spread and possible slippage. Never claim a guaranteed exit price or guaranteed protection.

## Required response

For every ticket include the action first, current position summary, two or three decisive reasons, exact modification levels/volumes, confidence (`alta`, `media`, or `baja`), and missing evidence. Keep it concise.

## Telegram payload

Pass a JSON object with `reviewed_at` and a non-empty `positions` array. Each position supports:

```json
{
  "asset": "GBPCAD",
  "ticket": "1982460641",
  "direction": "BUY",
  "action": "CERRAR_TODO",
  "urgency": "AHORA",
  "instruction": "Cerrar 0.25 lotes a mercado cerca de 1.87864.",
  "reasons": ["Cierre semanal inminente", "Queda poco recorrido hasta TP"],
  "confidence": "alta",
  "volume": 0.25,
  "entry": 1.87676,
  "current_price": 1.87864,
  "current_profit_usd": 30.69,
  "old_sl": 1.87567,
  "old_tp": 1.87903
}
```

For `MOVER_SL`, include `new_sl`; for `AJUSTAR_TP`, include `new_tp`; for `CIERRE_PARCIAL`, include `close_volume` and `remaining_volume`, plus protected levels for the remainder. The publisher rejects risk-increasing SL/TP changes.
