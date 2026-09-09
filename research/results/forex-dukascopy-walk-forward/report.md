# Forex strategy walk-forward research

## Design

- Data: Dukascopy M15 bid, 2025-12-01 through 2026-05-29.
- Symbols: EURUSD, GBPUSD, USDCAD, USDJPY.
- Chronological split: train through 2026-04-06; untouched validation from 2026-04-07.
- Tested configurations: 700 across 9 signal families.
- Execution: next-bar open, 8h maximum hold, maximum 3 trades/day.
- Costs: estimated spread plus 0.2 pip slippage; same-candle TP/SL ambiguity is counted as SL.

## Best training configuration per family

| Family | Configuration | Signals/Fills | Coverage | Avg R | Total R | PF | Max DD | Fold A/B Avg R |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| breakout | `breakout|overlap|rr=1.3|atr=1|lb=12|th=0|minq=0|trend|fixed` | 88/88 | 56.04% | 0.0583 | 5.1277 | 1.108 | 7.0367R | 0.0745 / 0.0465 |
| mean_reversion | `mean_reversion|core|rr=1.3|atr=1.3|lb=20|th=2|minq=0|raw|fixed` | 181/181 | 82.42% | -0.1202 | -21.7516 | 0.81 | 28.322R | -0.1611 / -0.0885 |
| momentum | `momentum|overlap|rr=1.6|atr=1.3|lb=16|th=0.7|minq=0|trend|fixed` | 200/200 | 80.22% | -0.0679 | -13.5824 | 0.899 | 25.3983R | -0.0317 / -0.097 |
| pending_breakout | `pending_breakout|overlap|rr=1.2|atr=1.6|lb=32|th=1|minq=0|trend|fixed` | 108/78 | 67.03% | 0.2244 | 17.507 | 1.519 | 4.5728R | 0.1015 / 0.31 |
| pullback_limit | `pullback_limit|core|rr=1.4|atr=1|lb=20|th=0.25|minq=0|trend|partial_08` | 204/156 | 83.52% | -0.0562 | -8.7721 | 0.86 | 18.9863R | 0.0234 / -0.1211 |
| session_breakout | `session_breakout|core|rr=1.3|atr=1.3|lb=20|th=0.1|minq=0|trend|fixed` | 146/146 | 73.63% | -0.2065 | -30.1498 | 0.693 | 31.3155R | -0.1992 / -0.2121 |
| session_pending | `session_pending|core|rr=1.6|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 149/68 | 79.12% | -0.3636 | -24.7232 | 0.558 | 24.9389R | -0.3524 / -0.3762 |
| strict_mtf | `strict_mtf|core|rr=1.6|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 66/66 | 41.76% | -0.2865 | -18.9097 | 0.622 | 24.4397R | -0.0832 / -0.4666 |
| trend_pullback | `trend_pullback|overlap|rr=1.6|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 79/79 | 56.04% | -0.1436 | -11.3426 | 0.796 | 14.686R | -0.1264 / -0.1587 |

## Untouched validation of the five training winners

| Rank | Configuration | Signals/Fills | Coverage | Win rate | Avg R | Total R | PF | Max DD |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `pending_breakout|overlap|rr=1.2|atr=1.6|lb=32|th=1|minq=0|trend|fixed` | 64/48 | 66.67% | 31.25% | -0.4825 | -23.1585 | 0.393 | 23.1585R |
| 2 | `pending_breakout|overlap|rr=1.2|atr=1.6|lb=32|th=1|minq=0.5|trend|fixed` | 55/42 | 61.54% | 33.33% | -0.4246 | -17.8329 | 0.45 | 17.8329R |
| 3 | `breakout|overlap|rr=1.3|atr=1|lb=12|th=0|minq=0|trend|fixed` | 43/43 | 56.41% | 37.21% | -0.4044 | -17.3909 | 0.486 | 18.0795R |
| 4 | `pending_breakout|overlap|rr=1.2|atr=1.6|lb=20|th=1|minq=0|trend|fixed` | 70/52 | 71.79% | 30.77% | -0.4933 | -25.6519 | 0.384 | 26.8142R |
| 5 | `pending_breakout|overlap|rr=1.2|atr=1.6|lb=20|th=1|minq=0.5|trend|fixed` | 61/44 | 66.67% | 31.82% | -0.4612 | -20.2909 | 0.417 | 20.2909R |

## Predeclared production gate

- Selected only from training: `pending_breakout|overlap|rr=1.2|atr=1.6|lb=32|th=1|minq=0|trend|fixed`.
- Validation 95% bootstrap interval for mean R/trade: [-0.7497, -0.1867].
- Cost stress (1.5x / 2.0x) average R: -0.5603 / -0.6381.
- Gate result: **FAIL — do not change production**.
- Reason: Failed: avg_r_at_least_0_10, profit_factor_at_least_1_20, positive_at_double_cost

## Daily validation

| Date | Trades | Net R |
| --- | ---: | ---: |
| 2026-04-07 | 2 | -2.2362 |
| 2026-04-08 | 1 | -1.0684 |
| 2026-04-09 | 0 | 0 |
| 2026-04-10 | 0 | 0 |
| 2026-04-13 | 0 | 0 |
| 2026-04-14 | 3 | 0.9626 |
| 2026-04-15 | 0 | 0 |
| 2026-04-16 | 1 | 0.3917 |
| 2026-04-17 | 2 | -0.2313 |
| 2026-04-20 | 0 | 0 |
| 2026-04-21 | 1 | -1.1713 |
| 2026-04-22 | 2 | -2.2569 |
| 2026-04-23 | 3 | -3.434 |
| 2026-04-24 | 0 | 0 |
| 2026-04-27 | 3 | -1.2187 |
| 2026-04-28 | 0 | 0 |
| 2026-04-29 | 3 | -1.227 |
| 2026-04-30 | 0 | 0 |
| 2026-05-01 | 3 | -1.1289 |
| 2026-05-04 | 0 | 0 |
| 2026-05-05 | 0 | 0 |
| 2026-05-06 | 0 | 0 |
| 2026-05-07 | 2 | -2.2667 |
| 2026-05-08 | 1 | -1.1436 |
| 2026-05-11 | 0 | 0 |
| 2026-05-12 | 2 | -0.2242 |
| 2026-05-13 | 3 | 0.9979 |
| 2026-05-14 | 3 | -1.3801 |
| 2026-05-15 | 2 | 0.0003 |
| 2026-05-18 | 0 | 0 |
| 2026-05-19 | 2 | -0.0963 |
| 2026-05-20 | 2 | -2.35 |
| 2026-05-21 | 2 | -0.1038 |
| 2026-05-22 | 3 | -3.76 |
| 2026-05-25 | 1 | 1.0512 |
| 2026-05-26 | 0 | 0 |
| 2026-05-27 | 1 | -1.2646 |
| 2026-05-28 | 0 | 0 |
| 2026-05-29 | 0 | 0 |

## Limits

- Dukascopy bid candles are historical quotes; ask-side execution and the actual FBS spread are estimated.
- Only four complete symbols are included because later Dukascopy requests were rate-limited.
- Swap, news-calendar filtering, variable spreads, rejected orders, and partial fills are not modeled.
- A positive result is a hypothesis for demo forward testing, not evidence of guaranteed future profit.
