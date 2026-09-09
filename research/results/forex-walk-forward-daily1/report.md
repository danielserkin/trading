# Forex strategy walk-forward research

## Design

- Data: Yahoo 15-minute midpoint proxy, 2026-06-17 through 2026-09-09.
- Symbols: AUDJPY, AUDUSD, EURAUD, EURGBP, EURJPY, EURUSD, GBPAUD, GBPCAD, GBPCHF, GBPJPY, GBPUSD, NZDUSD, USDCAD, USDCHF, USDJPY.
- Chronological split: train through 2026-08-13; untouched validation from 2026-08-14.
- Tested configurations: 700 across 9 signal families.
- Execution: next-bar open, 4h maximum hold, maximum 1 trades/day.
- Costs: estimated spread plus 0.2 pip slippage; same-candle TP/SL ambiguity is counted as SL.

## Best training configuration per family

| Family | Configuration | Signals/Fills | Coverage | Avg R | Total R | PF | Max DD | Fold A/B Avg R |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| breakout | `breakout|overlap|rr=1.6|atr=1.3|lb=12|th=0|minq=0|raw|fixed` | 33/33 | 78.57% | -0.1762 | -5.8153 | 0.76 | 9.5939R | -0.1641 / -0.1831 |
| mean_reversion | `mean_reversion|overlap|rr=1.3|atr=1.3|lb=20|th=1.5|minq=0|raw|fixed` | 33/33 | 78.57% | -0.2009 | -6.6309 | 0.697 | 7.673R | -0.0543 / -0.2847 |
| momentum | `momentum|core|rr=1.6|atr=1.3|lb=4|th=1.1|minq=0|trend|fixed` | 33/33 | 78.57% | -0.2016 | -6.6538 | 0.732 | 8.8162R | -0.0861 / -0.2676 |
| pending_breakout | `pending_breakout|core|rr=1.6|atr=1.6|lb=32|th=1|minq=0.5|trend|fixed` | 33/26 | 78.57% | 0.1642 | 4.2689 | 1.295 | 3.0168R | 0.0403 / 0.2551 |
| pullback_limit | `pullback_limit|overlap|rr=1|atr=2|lb=12|th=0.25|minq=0|trend|fixed` | 33/26 | 78.57% | 0.1703 | 4.4282 | 1.481 | 2.5812R | 0.2482 / 0.1416 |
| session_breakout | `session_breakout|core|rr=1.3|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 32/32 | 76.19% | -0.4342 | -13.8943 | 0.451 | 15.2956R | -0.5352 / -0.3813 |
| session_pending | `session_pending|core|rr=1.3|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 32/13 | 76.19% | -0.083 | -1.0788 | 0.86 | 3.0658R | 0.0434 / -0.162 |
| strict_mtf | `strict_mtf|core|rr=1.3|atr=1.3|lb=20|th=0|minq=0|trend|fixed` | 33/33 | 78.57% | -0.2187 | -7.2174 | 0.667 | 7.2174R | -0.4327 / -0.0964 |
| trend_pullback | `trend_pullback|core|rr=1.6|atr=1|lb=20|th=0|minq=0|trend|fixed` | 33/33 | 78.57% | -0.0247 | -0.8165 | 0.961 | 5.3651R | -0.1199 / 0.0296 |

## Untouched validation of the five training winners

| Rank | Configuration | Signals/Fills | Coverage | Win rate | Avg R | Total R | PF | Max DD |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `pullback_limit|overlap|rr=1|atr=2|lb=12|th=0.25|minq=0|trend|fixed` | 18/14 | 94.74% | 64.29% | 0.2101 | 2.9415 | 1.722 | 2.6951R |
| 2 | `pullback_limit|overlap|rr=1|atr=2|lb=12|th=0.25|minq=0.75|trend|fixed` | 18/15 | 94.74% | 66.67% | 0.2272 | 3.4079 | 1.846 | 2.6488R |
| 3 | `pullback_limit|overlap|rr=1.6|atr=2|lb=12|th=0.25|minq=0.75|trend|fixed` | 18/15 | 94.74% | 53.33% | 0.1526 | 2.2883 | 1.356 | 3.0653R |
| 4 | `pullback_limit|overlap|rr=1.4|atr=1.6|lb=12|th=0.25|minq=0|trend|fixed` | 18/14 | 94.74% | 57.14% | 0.1633 | 2.2867 | 1.344 | 4.2384R |
| 5 | `pullback_limit|overlap|rr=1.2|atr=1.6|lb=12|th=0.25|minq=0.75|trend|fixed` | 18/15 | 94.74% | 53.33% | 0.0085 | 0.1272 | 1.017 | 4.1805R |

## Predeclared production gate

- Selected only from training: `pullback_limit|overlap|rr=1|atr=2|lb=12|th=0.25|minq=0|trend|fixed`.
- Validation 95% bootstrap interval for mean R/trade: [-0.2479, 0.6201].
- Cost stress (1.5x / 2.0x) average R: 0.1144 / 0.0188.
- Gate result: **FAIL — do not change production**.
- Reason: Failed: at_least_15_validation_trades

## Daily validation

| Date | Trades | Net R |
| --- | ---: | ---: |
| 2026-08-14 | 1 | 0.8327 |
| 2026-08-17 | 1 | 0.8204 |
| 2026-08-18 | 0 | 0 |
| 2026-08-19 | 1 | 0.8192 |
| 2026-08-20 | 1 | 0.7841 |
| 2026-08-21 | 1 | 0.7044 |
| 2026-08-24 | 1 | -1.298 |
| 2026-08-25 | 1 | -1.2094 |
| 2026-08-26 | 1 | -0.1877 |
| 2026-08-27 | 1 | 0.6017 |
| 2026-08-28 | 0 | 0 |
| 2026-08-31 | 1 | 0.7717 |
| 2026-09-01 | 1 | -1.1711 |
| 2026-09-02 | 1 | 0.8364 |
| 2026-09-03 | 1 | 0.8468 |
| 2026-09-04 | 0 | 0 |
| 2026-09-07 | 1 | -0.2097 |
| 2026-09-08 | 0 | 0 |
| 2026-09-09 | 0 | 0 |

## Limits

- Yahoo candles are indicative midpoint proxies, not executable FBS bid/ask quotes.
- The sample is short because the public source limits 15-minute history to about 60 days.
- Swap, news-calendar filtering, variable spreads, rejected orders, and partial fills are not modeled.
- A positive result is a hypothesis for demo forward testing, not evidence of guaranteed future profit.
