# Forex strategy walk-forward research

## Design

- Data: Yahoo 15-minute midpoint proxy, 2026-06-17 through 2026-09-09.
- Symbols: AUDJPY, AUDUSD, EURAUD, EURGBP, EURJPY, EURUSD, GBPAUD, GBPCAD, GBPCHF, GBPJPY, GBPUSD, NZDUSD, USDCAD, USDCHF, USDJPY.
- Chronological split: train through 2026-08-13; untouched validation from 2026-08-14.
- Tested configurations: 700 across 9 signal families.
- Execution: next-bar open, 4h maximum hold, maximum 3 trades/day.
- Costs: estimated spread plus 0.2 pip slippage; same-candle TP/SL ambiguity is counted as SL.

## Best training configuration per family

| Family | Configuration | Signals/Fills | Coverage | Avg R | Total R | PF | Max DD | Fold A/B Avg R |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| breakout | `breakout|overlap|rr=1.6|atr=1.3|lb=12|th=0|minq=0|raw|fixed` | 99/99 | 78.57% | -0.1112 | -11.0109 | 0.84 | 21.3328R | -0.2705 / -0.0202 |
| mean_reversion | `mean_reversion|overlap|rr=1.6|atr=1.3|lb=20|th=1.5|minq=0|raw|fixed` | 99/99 | 78.57% | -0.2136 | -21.1442 | 0.709 | 25.8303R | 0.0566 / -0.368 |
| momentum | `momentum|overlap|rr=1.3|atr=1.3|lb=8|th=1.1|minq=0|trend|fixed` | 99/99 | 78.57% | -0.2442 | -24.1793 | 0.643 | 25.1996R | -0.2549 / -0.2382 |
| pending_breakout | `pending_breakout|core|rr=1.2|atr=1.6|lb=32|th=1|minq=0.5|trend|fixed` | 94/70 | 78.57% | -0.0524 | -3.6647 | 0.906 | 8.1488R | -0.0848 / -0.0307 |
| pullback_limit | `pullback_limit|overlap|rr=1.4|atr=2|lb=12|th=0.25|minq=0.75|trend|fixed` | 98/85 | 78.57% | 0.1583 | 13.4555 | 1.373 | 6.8639R | 0.2321 / 0.1137 |
| session_breakout | `session_breakout|core|rr=1.6|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 93/93 | 76.19% | -0.2746 | -25.534 | 0.624 | 29.0605R | -0.2238 / -0.2999 |
| session_pending | `session_pending|core|rr=1.3|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 91/31 | 76.19% | -0.3654 | -11.3263 | 0.506 | 11.3263R | -0.3863 / -0.3568 |
| strict_mtf | `strict_mtf|overlap|rr=1.3|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 72/72 | 73.81% | -0.2687 | -19.349 | 0.592 | 23.647R | -0.3884 / -0.188 |
| trend_pullback | `trend_pullback|core|rr=1.3|atr=1.3|lb=12|th=0|minq=0|trend|fixed` | 92/92 | 78.57% | -0.1933 | -17.7814 | 0.699 | 17.9804R | -0.141 / -0.2212 |

## Untouched validation of the five training winners

| Rank | Configuration | Signals/Fills | Coverage | Win rate | Avg R | Total R | PF | Max DD |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `pullback_limit|overlap|rr=1.4|atr=2|lb=12|th=0.25|minq=0.75|trend|fixed` | 54/40 | 94.74% | 65.0% | 0.3063 | 12.2525 | 2.053 | 3.6694R |
| 2 | `pullback_limit|overlap|rr=1.2|atr=2|lb=12|th=0.25|minq=0.75|trend|fixed` | 54/40 | 94.74% | 65.0% | 0.2374 | 9.4945 | 1.816 | 3.8085R |
| 3 | `pullback_limit|overlap|rr=1.6|atr=2|lb=12|th=0.25|minq=0.75|trend|fixed` | 54/40 | 94.74% | 65.0% | 0.3456 | 13.8231 | 2.188 | 3.6694R |
| 4 | `pullback_limit|overlap|rr=1|atr=2|lb=12|th=0.25|minq=0.75|trend|fixed` | 54/40 | 94.74% | 70.0% | 0.2705 | 10.8208 | 2.17 | 2.9363R |
| 5 | `pullback_limit|core|rr=1|atr=1.3|lb=20|th=0.25|minq=0|trend|fixed` | 54/41 | 94.74% | 68.29% | 0.0972 | 3.9861 | 1.24 | 2.9903R |

## Predeclared production gate

- Selected only from training: `pullback_limit|overlap|rr=1.4|atr=2|lb=12|th=0.25|minq=0.75|trend|fixed`.
- Validation 95% bootstrap interval for mean R/trade: [0.006, 0.5814].
- Cost stress (1.5x / 2.0x) average R: 0.229 / 0.1517.
- Gate result: **PASS — eligible for demo forward test**.
- Reason: All robustness conditions passed.

## Daily validation

| Date | Trades | Net R |
| --- | ---: | ---: |
| 2026-08-14 | 3 | 0.1494 |
| 2026-08-17 | 2 | -0.3811 |
| 2026-08-18 | 2 | 1.4517 |
| 2026-08-19 | 1 | 1.322 |
| 2026-08-20 | 3 | 3.3809 |
| 2026-08-21 | 2 | 2.4138 |
| 2026-08-24 | 2 | -1.7733 |
| 2026-08-25 | 3 | -0.7663 |
| 2026-08-26 | 3 | 1.8337 |
| 2026-08-27 | 3 | 2.0362 |
| 2026-08-28 | 2 | 2.4255 |
| 2026-08-31 | 1 | -1.2283 |
| 2026-09-01 | 3 | -2.4412 |
| 2026-09-02 | 2 | 0.061 |
| 2026-09-03 | 2 | 2.5929 |
| 2026-09-04 | 3 | 2.3316 |
| 2026-09-07 | 1 | -0.2097 |
| 2026-09-08 | 2 | -0.9464 |
| 2026-09-09 | 0 | 0 |

## Limits

- Yahoo candles are indicative midpoint proxies, not executable FBS bid/ask quotes.
- The sample is short because the public source limits 15-minute history to about 60 days.
- Swap, news-calendar filtering, variable spreads, rejected orders, and partial fills are not modeled.
- A positive result is a hypothesis for demo forward testing, not evidence of guaranteed future profit.
