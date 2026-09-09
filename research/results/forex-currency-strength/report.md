# Cross-sectional currency-strength walk-forward

- Data: Yahoo hourly midpoint proxy, 2024-09-09 through 2026-09-09, 15 pairs.
- Chronological split: train through 2026-02-02; untouched validation starts 2026-02-03.
- Search: 2592 combinations of momentum/reversal, 1–3 cards, correlation filter, entry hour, stop, RR and hold.
- Execution: signal after an hourly close, next-hour entry, estimated cost, conservative SL on same-bar ambiguity.

## Training winner

`momentum|lb=120h|min=0|stop=1.8atr|rr=1|hold=24h|cards=1|utc=12|shared_ok`

- Train: 360 trades, 10.02R, avg 0.028R, PF 1.06, coverage 98.4%.
- Validation: 156 trades, -8.17R, avg -0.052R, PF 0.89, max DD 20.21R, coverage 99.4%.
- Double-cost validation: -18.30R, avg -0.117R.
- Gate: **FAIL — do not deploy** — Failed: avg_r_at_least_0_08, profit_factor_at_least_1_20, max_drawdown_below_12r, positive_at_double_cost

## Top five selected only on training

| Rank | Configuration | Train avg/PF | Validation avg/PF | Validation R |
|---:|---|---:|---:|---:|
| 1 | `momentum|lb=120h|min=0|stop=1.8atr|rr=1|hold=24h|cards=1|utc=12|shared_ok` | 0.028 / 1.06 | -0.052 / 0.89 | -8.17 |
| 2 | `momentum|lb=120h|min=0|stop=1.8atr|rr=1|hold=24h|cards=1|utc=12|disjoint` | 0.028 / 1.06 | -0.052 / 0.89 | -8.17 |
| 3 | `momentum|lb=120h|min=0.5|stop=1.8atr|rr=1|hold=24h|cards=1|utc=12|shared_ok` | 0.028 / 1.06 | -0.052 / 0.89 | -8.17 |
| 4 | `momentum|lb=120h|min=0.5|stop=1.8atr|rr=1|hold=24h|cards=1|utc=12|disjoint` | 0.028 / 1.06 | -0.052 / 0.89 | -8.17 |
| 5 | `momentum|lb=120h|min=1|stop=1.8atr|rr=1|hold=24h|cards=1|utc=12|shared_ok` | 0.028 / 1.06 | -0.052 / 0.89 | -8.17 |

## Limits

- Yahoo prices are indicative, not executable FBS bid/ask quotes.
- This intraday currency-strength formulation is inspired by cross-sectional FX momentum, but it is not the monthly academic portfolio construction.
- Interest-rate carry, macro releases, variable spreads, swaps and rejected orders are not modeled.
- No production setting is changed by this research.
