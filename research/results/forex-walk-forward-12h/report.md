# Forex strategy walk-forward research

## Design

- Data: Yahoo 15-minute midpoint proxy, 2026-06-17 through 2026-09-09.
- Symbols: AUDJPY, AUDUSD, EURAUD, EURGBP, EURJPY, EURUSD, GBPAUD, GBPCAD, GBPCHF, GBPJPY, GBPUSD, NZDUSD, USDCAD, USDCHF, USDJPY.
- Chronological split: train through 2026-08-13; untouched validation from 2026-08-14.
- Tested configurations: 700 across 9 signal families.
- Execution: next-bar open, 12h maximum hold, maximum 3 trades/day.
- Costs: estimated spread plus 0.2 pip slippage; same-candle TP/SL ambiguity is counted as SL.

## Best training configuration per family

| Family | Configuration | Signals/Fills | Coverage | Avg R | Total R | PF | Max DD | Fold A/B Avg R |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| breakout | `breakout|overlap|rr=1.6|atr=1.3|lb=20|th=0|minq=0|raw|fixed` | 99/99 | 78.57% | -0.1245 | -12.3296 | 0.827 | 21.001R | -0.2789 / -0.0364 |
| mean_reversion | `mean_reversion|overlap|rr=1.6|atr=1.3|lb=20|th=1.5|minq=0|raw|fixed` | 99/99 | 78.57% | -0.2046 | -20.2527 | 0.726 | 24.9388R | 0.0645 / -0.3583 |
| momentum | `momentum|core|rr=1.6|atr=1.3|lb=8|th=0.7|minq=0|trend|fixed` | 99/99 | 78.57% | -0.1877 | -18.5809 | 0.746 | 23.0512R | -0.0496 / -0.2666 |
| pending_breakout | `pending_breakout|core|rr=1.2|atr=1.6|lb=32|th=1|minq=0.5|trend|fixed` | 94/70 | 78.57% | -0.0818 | -5.7265 | 0.863 | 8.9407R | -0.126 / -0.0524 |
| pullback_limit | `pullback_limit|overlap|rr=1.4|atr=2|lb=12|th=0.25|minq=0.75|trend|fixed` | 98/86 | 78.57% | 0.1323 | 11.374 | 1.263 | 5.5182R | 0.2029 / 0.0904 |
| session_breakout | `session_breakout|core|rr=1.3|atr=1|lb=20|th=0|minq=0|trend|fixed` | 93/93 | 76.19% | -0.3037 | -28.2415 | 0.583 | 33.954R | -0.273 / -0.319 |
| session_pending | `session_pending|core|rr=1.3|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 91/31 | 76.19% | -0.3336 | -10.3415 | 0.549 | 10.3415R | -0.2769 / -0.3568 |
| strict_mtf | `strict_mtf|core|rr=1.3|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 86/86 | 78.57% | -0.3138 | -26.9905 | 0.572 | 31.028R | -0.3271 / -0.3056 |
| trend_pullback | `trend_pullback|core|rr=1.3|atr=1.3|lb=12|th=0|minq=0|trend|fixed` | 92/92 | 78.57% | -0.1668 | -15.3449 | 0.748 | 18.4613R | -0.0677 / -0.2196 |

## Untouched validation of the five training winners

| Rank | Configuration | Signals/Fills | Coverage | Win rate | Avg R | Total R | PF | Max DD |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `pullback_limit|overlap|rr=1.4|atr=2|lb=12|th=0.25|minq=0.75|trend|fixed` | 54/40 | 94.74% | 62.5% | 0.3147 | 12.5873 | 1.759 | 4.7051R |
| 2 | `pullback_limit|core|rr=1|atr=1.3|lb=20|th=0.25|minq=0|trend|fixed` | 54/41 | 94.74% | 68.29% | 0.0706 | 2.8927 | 1.163 | 2.9903R |
| 3 | `pullback_limit|overlap|rr=1.4|atr=2|lb=12|th=0.25|minq=0|trend|fixed` | 54/37 | 94.74% | 62.16% | 0.3241 | 11.9916 | 1.777 | 6.5796R |
| 4 | `pullback_limit|overlap|rr=1.6|atr=2|lb=12|th=0.25|minq=0.75|trend|fixed` | 54/40 | 94.74% | 60.0% | 0.3647 | 14.5873 | 1.821 | 6.5923R |
| 5 | `pullback_limit|overlap|rr=1.2|atr=2|lb=12|th=0.25|minq=0|trend|fixed` | 54/37 | 94.74% | 62.16% | 0.2052 | 7.5916 | 1.492 | 6.5796R |

## Predeclared production gate

- Selected only from training: `pullback_limit|overlap|rr=1.4|atr=2|lb=12|th=0.25|minq=0.75|trend|fixed`.
- Validation 95% bootstrap interval for mean R/trade: [-0.0482, 0.6502].
- Cost stress (1.5x / 2.0x) average R: 0.2374 / 0.16.
- Gate result: **PASS — eligible for demo forward test**.
- Reason: All robustness conditions passed.

## Daily validation

| Date | Trades | Net R |
| --- | ---: | ---: |
| 2026-08-14 | 3 | 0.1616 |
| 2026-08-17 | 2 | 0.1385 |
| 2026-08-18 | 2 | 0.6672 |
| 2026-08-19 | 1 | 1.322 |
| 2026-08-20 | 3 | 3.782 |
| 2026-08-21 | 2 | 2.4138 |
| 2026-08-24 | 2 | -2.4244 |
| 2026-08-25 | 3 | -1.0681 |
| 2026-08-26 | 3 | 1.7636 |
| 2026-08-27 | 3 | 1.1326 |
| 2026-08-28 | 2 | 2.4255 |
| 2026-08-31 | 1 | -1.2283 |
| 2026-09-01 | 3 | -1.1272 |
| 2026-09-02 | 2 | 0.061 |
| 2026-09-03 | 2 | 2.5929 |
| 2026-09-04 | 3 | 3.9427 |
| 2026-09-07 | 1 | -1.1618 |
| 2026-09-08 | 2 | -0.8062 |
| 2026-09-09 | 0 | 0 |

## Limits

- Yahoo candles are indicative midpoint proxies, not executable FBS bid/ask quotes.
- The sample is short because the public source limits 15-minute history to about 60 days.
- Swap, news-calendar filtering, variable spreads, rejected orders, and partial fills are not modeled.
- A positive result is a hypothesis for demo forward testing, not evidence of guaranteed future profit.
