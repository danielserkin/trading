# Adaptive FX nested walk-forward

- Data: Dukascopy M15 bid, 2025-12-01 through 2026-05-29 (EURUSD, GBPUSD, USDCAD, USDJPY).
- Base search space: 700 configurations across 9 families.
- Meta-training evaluation: 2026-02-23 through 2026-04-06.
- Untouched final validation: 2026-04-07 through 2026-05-29.
- Frozen adaptive rule: `trail=45|rebalance=10|minfills=10|full_positive`.

## Result

- Meta-training: 44 signals / 30 fills, 10.77R, avg 0.359R, PF 1.87.
- Final validation: 63 signals / 55 fills, -24.36R, avg -0.443R, PF 0.44, max DD 29.09R.
- Validation coverage: 76.9% of trading days; double-cost total -33.92R.
- Production gate: **FAIL — do not deploy** — Failed: avg_r_at_least_0_10, profit_factor_at_least_1_20, positive_at_double_cost

## Point-in-time decisions

| Test block | Selected family/config | Prior fills / avg R | Block fills / R |
|---|---|---:|---:|
| 2026-04-07–2026-04-20 | pending_breakout / `pending_breakout|overlap|rr=1.6|atr=1.6|lb=20|th=0.6|minq=0|trend|fixed` | 46 / 0.395 | 7 / -2.76 |
| 2026-04-21–2026-05-04 | pending_breakout / `pending_breakout|overlap|rr=1.6|atr=1.6|lb=20|th=1|minq=0|trend|fixed` | 58 / 0.256 | 16 / -7.79 |
| 2026-05-05–2026-05-18 | trend_pullback / `trend_pullback|core|rr=1.6|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 50 / 0.304 | 16 / -16.59 |
| 2026-05-19–2026-05-29 | pullback_limit / `pullback_limit|overlap|rr=1|atr=1.6|lb=12|th=0.25|minq=0.75|trend|fixed` | 52 / 0.222 | 16 / 2.78 |

## Hindsight diagnostic (not tradable)

Choosing the best configuration only after seeing each validation block would produce 29.92R over 69 fills. This proves that profitable paths existed, not that they were identifiable beforehand.

## Limits

- Only four pairs were available in the independent Dukascopy download because the remaining requests were rate-limited.
- Repeated testing across many configurations creates selection risk; the nested final segment reduces but does not remove it.
- Spread and slippage are estimates; no macroeconomic-calendar or order-book inputs are modeled.
- No production setting is changed by this research.
