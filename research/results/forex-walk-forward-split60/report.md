# Forex strategy walk-forward research

## Design

- Data: Yahoo 15-minute midpoint proxy, 2026-06-17 through 2026-09-09.
- Symbols: AUDJPY, AUDUSD, EURAUD, EURGBP, EURJPY, EURUSD, GBPAUD, GBPCAD, GBPCHF, GBPJPY, GBPUSD, NZDUSD, USDCAD, USDCHF, USDJPY.
- Chronological split: train through 2026-08-05; untouched validation from 2026-08-06.
- Tested configurations: 700 across 9 signal families.
- Execution: next-bar open, 8h maximum hold, maximum 3 trades/day.
- Costs: estimated spread plus 0.2 pip slippage; same-candle TP/SL ambiguity is counted as SL.

## Best training configuration per family

| Family | Configuration | Signals/Fills | Coverage | Avg R | Total R | PF | Max DD | Fold A/B Avg R |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| breakout | `breakout|overlap|rr=1.6|atr=1.3|lb=12|th=0|minq=0|raw|fixed` | 81/81 | 75.0% | -0.1955 | -15.8339 | 0.738 | 20.6256R | -0.3507 / -0.1179 |
| mean_reversion | `mean_reversion|overlap|rr=1.6|atr=1.3|lb=32|th=2|minq=0|raw|fixed` | 80/80 | 75.0% | -0.1099 | -8.7933 | 0.843 | 18.1968R | 0.0523 / -0.188 |
| momentum | `momentum|core|rr=1.6|atr=1.3|lb=8|th=0.7|minq=0|trend|fixed` | 81/81 | 75.0% | -0.1119 | -9.0633 | 0.839 | 12.2132R | -0.0244 / -0.1557 |
| pending_breakout | `pending_breakout|core|rr=1.2|atr=1.6|lb=12|th=0.6|minq=0|trend|fixed` | 78/65 | 75.0% | -0.0609 | -3.9562 | 0.891 | 11.497R | -0.0141 / -0.0832 |
| pullback_limit | `pullback_limit|overlap|rr=1|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 81/70 | 75.0% | 0.0859 | 6.0096 | 1.207 | 4.7548R | 0.186 / 0.0369 |
| session_breakout | `session_breakout|core|rr=1.6|atr=1|lb=20|th=0|minq=0|trend|fixed` | 76/76 | 72.22% | -0.3001 | -22.8094 | 0.622 | 27.0204R | -0.5043 / -0.2169 |
| session_pending | `session_pending|core|rr=1.6|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 73/26 | 72.22% | -0.2952 | -7.6754 | 0.618 | 10.2783R | -0.5625 / -0.1967 |
| strict_mtf | `strict_mtf|overlap|rr=1.3|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 62/62 | 72.22% | -0.3749 | -23.242 | 0.5 | 25.0918R | -0.265 / -0.4353 |
| trend_pullback | `trend_pullback|core|rr=1.3|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 75/75 | 75.0% | -0.1008 | -7.5592 | 0.839 | 14.2069R | -0.1381 / -0.0843 |

## Untouched validation of the five training winners

| Rank | Configuration | Signals/Fills | Coverage | Win rate | Avg R | Total R | PF | Max DD |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `pullback_limit|overlap|rr=1|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 72/61 | 96.0% | 67.21% | 0.0815 | 4.9694 | 1.201 | 5.8451R |
| 2 | `pullback_limit|core|rr=1|atr=1.3|lb=20|th=0.25|minq=0|trend|fixed` | 72/58 | 96.0% | 70.69% | 0.1257 | 7.293 | 1.321 | 2.9903R |
| 3 | `pullback_limit|overlap|rr=1.2|atr=2|lb=12|th=0.25|minq=0.75|trend|fixed` | 71/54 | 96.0% | 62.96% | 0.1915 | 10.3422 | 1.481 | 4.7051R |
| 4 | `pullback_limit|overlap|rr=1.6|atr=2|lb=20|th=0|minq=0.75|trend|partial_08` | 72/62 | 96.0% | 69.35% | 0.0857 | 5.3155 | 1.25 | 7.218R |
| 5 | `pullback_limit|overlap|rr=1.4|atr=1.6|lb=20|th=0|minq=0|trend|partial_08` | 72/62 | 96.0% | 67.74% | -0.0194 | -1.2053 | 0.945 | 9.5617R |

## Predeclared production gate

- Selected only from training: `pullback_limit|overlap|rr=1|atr=1.3|lb=20|th=0|minq=0|trend|fixed`.
- Validation 95% bootstrap interval for mean R/trade: [-0.1591, 0.3169].
- Cost stress (1.5x / 2.0x) average R: -0.0663 / -0.2141.
- Gate result: **FAIL — do not change production**.
- Reason: Failed: avg_r_at_least_0_10, positive_at_double_cost

## Daily validation

| Date | Trades | Net R |
| --- | ---: | ---: |
| 2026-08-06 | 3 | 0.0532 |
| 2026-08-07 | 3 | 0.3438 |
| 2026-08-10 | 3 | 0.4406 |
| 2026-08-11 | 3 | -0.4098 |
| 2026-08-12 | 3 | 0.9132 |
| 2026-08-13 | 2 | -0.4418 |
| 2026-08-14 | 3 | 2.2362 |
| 2026-08-17 | 2 | 1.606 |
| 2026-08-18 | 1 | 0.8447 |
| 2026-08-19 | 3 | 1.8103 |
| 2026-08-20 | 3 | 0.3099 |
| 2026-08-21 | 3 | 2.1439 |
| 2026-08-24 | 2 | -0.653 |
| 2026-08-25 | 3 | -3.5992 |
| 2026-08-26 | 3 | 2.4555 |
| 2026-08-27 | 3 | -1.8729 |
| 2026-08-28 | 2 | 1.3425 |
| 2026-08-31 | 2 | -0.7667 |
| 2026-09-01 | 3 | -0.0007 |
| 2026-09-02 | 2 | -2.5843 |
| 2026-09-03 | 2 | 1.5664 |
| 2026-09-04 | 3 | -1.7327 |
| 2026-09-07 | 2 | 1.6319 |
| 2026-09-08 | 2 | -0.6675 |
| 2026-09-09 | 0 | 0 |

## Limits

- Yahoo candles are indicative midpoint proxies, not executable FBS bid/ask quotes.
- The sample is short because the public source limits 15-minute history to about 60 days.
- Swap, news-calendar filtering, variable spreads, rejected orders, and partial fills are not modeled.
- A positive result is a hypothesis for demo forward testing, not evidence of guaranteed future profit.
