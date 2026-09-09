# Forex strategy walk-forward research

## Design

- Data: Yahoo 15-minute midpoint proxy, 2026-06-17 through 2026-09-09.
- Symbols: AUDJPY, AUDUSD, EURAUD, EURGBP, EURJPY, EURUSD, GBPAUD, GBPCAD, GBPCHF, GBPJPY, GBPUSD, NZDUSD, USDCAD, USDCHF, USDJPY.
- Chronological split: train through 2026-08-13; untouched validation from 2026-08-14.
- Tested configurations: 700 across 9 signal families.
- Execution: next-bar open, 4h maximum hold, maximum 2 trades/day.
- Costs: estimated spread plus 0.2 pip slippage; same-candle TP/SL ambiguity is counted as SL.

## Best training configuration per family

| Family | Configuration | Signals/Fills | Coverage | Avg R | Total R | PF | Max DD | Fold A/B Avg R |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| breakout | `breakout|overlap|rr=1.6|atr=1.3|lb=12|th=0|minq=0|raw|fixed` | 66/66 | 78.57% | -0.0345 | -2.2798 | 0.948 | 9.7048R | -0.1987 / 0.0593 |
| mean_reversion | `mean_reversion|core|rr=1.3|atr=1|lb=20|th=1.5|minq=0|raw|fixed` | 66/66 | 78.57% | -0.1991 | -13.1394 | 0.71 | 20.618R | -0.186 / -0.2066 |
| momentum | `momentum|core|rr=1.6|atr=1|lb=4|th=0.7|minq=0|trend|fixed` | 66/66 | 78.57% | -0.2081 | -13.7367 | 0.721 | 14.5609R | -0.2478 / -0.1855 |
| pending_breakout | `pending_breakout|overlap|rr=1.6|atr=1.3|lb=32|th=1|minq=0.5|trend|fixed` | 61/46 | 76.19% | 0.0316 | 1.4554 | 1.055 | 7.7551R | 0.1058 / -0.0205 |
| pullback_limit | `pullback_limit|overlap|rr=1.2|atr=1|lb=12|th=0.25|minq=0|trend|fixed` | 66/55 | 78.57% | 0.2156 | 11.856 | 1.548 | 4.176R | 0.3997 / 0.1184 |
| session_breakout | `session_breakout|core|rr=1.6|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 64/64 | 76.19% | -0.2301 | -14.7254 | 0.673 | 17.1044R | -0.1996 / -0.246 |
| session_pending | `session_pending|core|rr=1.3|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 62/25 | 76.19% | -0.3099 | -7.7474 | 0.561 | 8.0478R | -0.294 / -0.3174 |
| strict_mtf | `strict_mtf|core|rr=1.6|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 63/63 | 78.57% | -0.2459 | -15.4928 | 0.663 | 19.4873R | -0.3342 / -0.1916 |
| trend_pullback | `trend_pullback|core|rr=1.3|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 65/65 | 78.57% | -0.1412 | -9.1776 | 0.768 | 13.2593R | -0.041 / -0.1961 |

## Untouched validation of the five training winners

| Rank | Configuration | Signals/Fills | Coverage | Win rate | Avg R | Total R | PF | Max DD |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `pullback_limit|overlap|rr=1.2|atr=1|lb=12|th=0.25|minq=0|trend|fixed` | 36/24 | 94.74% | 62.5% | 0.0094 | 0.2253 | 1.018 | 6.0215R |
| 2 | `pullback_limit|overlap|rr=1.6|atr=2|lb=12|th=0.25|minq=0|trend|fixed` | 36/23 | 94.74% | 65.22% | 0.3446 | 7.9252 | 2.041 | 3.84R |
| 3 | `pullback_limit|overlap|rr=1.4|atr=2|lb=12|th=0.25|minq=0|trend|fixed` | 36/23 | 94.74% | 65.22% | 0.32 | 7.3597 | 1.966 | 3.84R |
| 4 | `pullback_limit|overlap|rr=1|atr=2|lb=12|th=0.25|minq=0|trend|fixed` | 36/23 | 94.74% | 73.91% | 0.3429 | 7.886 | 2.51 | 3.84R |
| 5 | `pullback_limit|overlap|rr=1.2|atr=2|lb=12|th=0.25|minq=0|trend|fixed` | 36/23 | 94.74% | 65.22% | 0.233 | 5.3597 | 1.704 | 3.84R |

## Predeclared production gate

- Selected only from training: `pullback_limit|overlap|rr=1.2|atr=1|lb=12|th=0.25|minq=0|trend|fixed`.
- Validation 95% bootstrap interval for mean R/trade: [-0.4406, 0.4405].
- Cost stress (1.5x / 2.0x) average R: -0.1734 / -0.3562.
- Gate result: **FAIL — do not change production**.
- Reason: Failed: avg_r_at_least_0_10, profit_factor_at_least_1_20, positive_at_double_cost

## Daily validation

| Date | Trades | Net R |
| --- | ---: | ---: |
| 2026-08-14 | 2 | 1.6655 |
| 2026-08-17 | 1 | -1.3592 |
| 2026-08-18 | 0 | 0 |
| 2026-08-19 | 1 | 0.8384 |
| 2026-08-20 | 2 | -0.4383 |
| 2026-08-21 | 2 | 1.6276 |
| 2026-08-24 | 1 | -1.5959 |
| 2026-08-25 | 2 | -0.5086 |
| 2026-08-26 | 2 | -2.7432 |
| 2026-08-27 | 2 | 1.7205 |
| 2026-08-28 | 1 | -1.4377 |
| 2026-08-31 | 1 | -1.4566 |
| 2026-09-01 | 2 | 1.4608 |
| 2026-09-02 | 1 | 0.8728 |
| 2026-09-03 | 2 | 1.8363 |
| 2026-09-04 | 1 | -1.1333 |
| 2026-09-07 | 1 | 0.8763 |
| 2026-09-08 | 0 | 0 |
| 2026-09-09 | 0 | 0 |

## Limits

- Yahoo candles are indicative midpoint proxies, not executable FBS bid/ask quotes.
- The sample is short because the public source limits 15-minute history to about 60 days.
- Swap, news-calendar filtering, variable spreads, rejected orders, and partial fills are not modeled.
- A positive result is a hypothesis for demo forward testing, not evidence of guaranteed future profit.
