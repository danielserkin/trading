# Forex strategy walk-forward research

## Design

- Data: Yahoo 15-minute midpoint proxy, 2026-06-17 through 2026-09-09.
- Symbols: AUDJPY, AUDUSD, EURAUD, EURGBP, EURJPY, EURUSD, GBPAUD, GBPCAD, GBPCHF, GBPJPY, GBPUSD, NZDUSD, USDCAD, USDCHF, USDJPY.
- Chronological split: train through 2026-08-21; untouched validation from 2026-08-24.
- Tested configurations: 700 across 9 signal families.
- Execution: next-bar open, 8h maximum hold, maximum 3 trades/day.
- Costs: estimated spread plus 0.2 pip slippage; same-candle TP/SL ambiguity is counted as SL.

## Best training configuration per family

| Family | Configuration | Signals/Fills | Coverage | Avg R | Total R | PF | Max DD | Fold A/B Avg R |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| breakout | `breakout|overlap|rr=1.6|atr=1.3|lb=20|th=0|minq=0|raw|fixed` | 117/117 | 81.25% | -0.121 | -14.1544 | 0.827 | 21.001R | -0.1505 / -0.1025 |
| mean_reversion | `mean_reversion|overlap|rr=1.6|atr=1.3|lb=32|th=2|minq=0|raw|fixed` | 116/116 | 81.25% | -0.2729 | -31.6621 | 0.655 | 36.1156R | -0.0674 / -0.3985 |
| momentum | `momentum|overlap|rr=1.6|atr=1.3|lb=16|th=1.1|minq=0|trend|fixed` | 117/117 | 81.25% | -0.2394 | -28.0051 | 0.681 | 35.6883R | -0.2107 / -0.2573 |
| pending_breakout | `pending_breakout|overlap|rr=1.2|atr=1.6|lb=32|th=1|minq=0.5|trend|fixed` | 105/78 | 79.17% | -0.0369 | -2.8811 | 0.933 | 10.724R | -0.0885 / -0.0081 |
| pullback_limit | `pullback_limit|overlap|rr=1.2|atr=2|lb=12|th=0.25|minq=0|trend|fixed` | 117/93 | 81.25% | 0.2187 | 20.3346 | 1.538 | 7.062R | 0.2031 / 0.2289 |
| session_breakout | `session_breakout|core|rr=1.6|atr=1|lb=20|th=0|minq=0|trend|fixed` | 106/106 | 77.08% | -0.1903 | -20.1685 | 0.744 | 33.8163R | -0.2157 / -0.1748 |
| session_pending | `session_pending|core|rr=1.3|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 108/42 | 79.17% | -0.2524 | -10.6004 | 0.642 | 13.5259R | -0.2396 / -0.2569 |
| strict_mtf | `strict_mtf|overlap|rr=1.3|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 82/82 | 75.0% | -0.2581 | -21.1668 | 0.624 | 25.6479R | -0.358 / -0.1874 |
| trend_pullback | `trend_pullback|overlap|rr=1.3|atr=1.3|lb=12|th=0|minq=0|trend|fixed` | 101/101 | 77.08% | -0.1917 | -19.3617 | 0.711 | 24.0356R | -0.2109 / -0.1815 |

## Untouched validation of the five training winners

| Rank | Configuration | Signals/Fills | Coverage | Win rate | Avg R | Total R | PF | Max DD |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `pullback_limit|overlap|rr=1.2|atr=2|lb=12|th=0.25|minq=0|trend|fixed` | 36/24 | 92.31% | 54.17% | 0.0557 | 1.3374 | 1.11 | 6.2285R |
| 2 | `pullback_limit|overlap|rr=1.2|atr=2|lb=12|th=0.25|minq=0.75|trend|fixed` | 36/27 | 92.31% | 55.56% | 0.0612 | 1.6532 | 1.124 | 4.7051R |
| 3 | `pullback_limit|overlap|rr=1|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 36/29 | 92.31% | 55.17% | -0.1683 | -4.8806 | 0.708 | 5.8451R |
| 4 | `pullback_limit|overlap|rr=1.4|atr=2|lb=12|th=0.25|minq=0.75|trend|partial_08` | 36/27 | 92.31% | 74.07% | 0.1362 | 3.6785 | 1.492 | 2.1875R |
| 5 | `pullback_limit|overlap|rr=1.6|atr=1.6|lb=12|th=0.25|minq=0|trend|fixed` | 36/24 | 92.31% | 45.83% | 0.0081 | 0.1941 | 1.013 | 7.8948R |

## Predeclared production gate

- Selected only from training: `pullback_limit|overlap|rr=1.2|atr=2|lb=12|th=0.25|minq=0|trend|fixed`.
- Validation 95% bootstrap interval for mean R/trade: [-0.3918, 0.4997].
- Cost stress (1.5x / 2.0x) average R: -0.0289 / -0.1135.
- Gate result: **FAIL — do not change production**.
- Reason: Failed: avg_r_at_least_0_10, profit_factor_at_least_1_20, positive_at_double_cost

## Daily validation

| Date | Trades | Net R |
| --- | ---: | ---: |
| 2026-08-24 | 2 | -2.4244 |
| 2026-08-25 | 3 | -3.4554 |
| 2026-08-26 | 3 | 1.7147 |
| 2026-08-27 | 3 | 0.7326 |
| 2026-08-28 | 2 | 2.0255 |
| 2026-08-31 | 1 | -1.2283 |
| 2026-09-01 | 3 | 0.8053 |
| 2026-09-02 | 2 | -0.1391 |
| 2026-09-03 | 2 | 2.1929 |
| 2026-09-04 | 2 | 2.2754 |
| 2026-09-07 | 1 | -1.1618 |
| 2026-09-08 | 0 | 0 |
| 2026-09-09 | 0 | 0 |

## Limits

- Yahoo candles are indicative midpoint proxies, not executable FBS bid/ask quotes.
- The sample is short because the public source limits 15-minute history to about 60 days.
- Swap, news-calendar filtering, variable spreads, rejected orders, and partial fills are not modeled.
- A positive result is a hypothesis for demo forward testing, not evidence of guaranteed future profit.
