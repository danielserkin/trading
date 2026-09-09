# Telegram provider walk-forward

- Captures: 21 files, 2980 repeated rows, 1360 unique messages.
- Structurally testable after conservative cleanup: 323.
- Price proxy: Yahoo 15-minute data; period 2026-08-03 through 2026-08-27.
- Selection slice ends 2026-08-18; untouched validation starts 2026-08-19.
- Execution: first complete bar after publication, stated entry or near-market next open, all-in cost estimate, stop wins same-bar ambiguity.

## Current providers

| Provider | Complete | 12h train fills / R | 12h validation fills / R | Validation PF |
|---|---:|---:|---:|---:|
| pipxpert | 11 | 1 / 0.26 | 1 / -0.53 | 0.00 |
| nasgold1 | 12 | 3 / 0.44 | 3 / -0.78 | 0.51 |
| learn2tradenews | 19 | 0 / 0.00 | 4 / -0.16 | 0.00 |
| forexvisitsignals | 73 | 29 / -4.50 | 15 / 1.30 | 1.19 |
| unitedsignalsfx | 37 | 11 / -2.00 | 9 / -0.97 | 0.80 |
| gold_signals | 29 | 6 / -2.99 | 5 / -4.13 | 0.12 |

## Rules selected without validation hindsight

### 4.0 hour exit

Selected on training: `current|minRR=0.5|market=all|hours=all`.

- Training: 44 signals, 21 fills, 4.62R, avg 0.220R, PF 1.64.
- Validation: 27 signals, 12 fills, -1.06R, avg -0.088R, PF 0.78, signal-day coverage 100.0%.
- Gate: **FAIL — do not deploy** — Failed: avg_r_above_0_05, profit_factor_above_1_15

### 12.0 hour exit

Selected on training: `current|minRR=0.5|market=all|hours=all`.

- Training: 44 signals, 21 fills, 3.03R, avg 0.144R, PF 1.34.
- Validation: 27 signals, 12 fills, -2.21R, avg -0.184R, PF 0.67, signal-day coverage 100.0%.
- Gate: **FAIL — do not deploy** — Failed: avg_r_above_0_05, profit_factor_above_1_15

### 24.0 hour exit

Selected on training: `current|minRR=0.5|market=all|hours=all`.

- Training: 44 signals, 21 fills, 1.42R, avg 0.068R, PF 1.14.
- Validation: 27 signals, 12 fills, -0.61R, avg -0.051R, PF 0.91, signal-day coverage 100.0%.
- Gate: **FAIL — do not deploy** — Failed: avg_r_above_0_05, profit_factor_above_1_15

## Disabled-provider diagnostic

This table uses a separate chronological split inside each provider. It can nominate channels to recapture, but cannot authorize production because most stopped producing captured messages before the global validation period.

| Provider | Fills | Earlier R | Later R | Later PF | Diagnostic |
|---|---:|---:|---:|---:|---|
| technicalpips6273 | 2 | 0.38 | 0.38 | 999.00 | insufficient sample |
| nassniperhuk50 | 2 | 0.25 | 0.23 | 999.00 | insufficient sample |
| forexvisitsignals | 44 | -4.50 | 1.30 | 1.19 | unstable/negative |
| pipxpert | 2 | -0.27 | 0.00 | 0.00 | insufficient sample |
| briantradingforex | 0 | 0.00 | 0.00 | 0.00 | insufficient sample |
| goldvlp7 | 0 | 0.00 | 0.00 | 0.00 | insufficient sample |
| tradewith_forexking786 | 0 | 0.00 | 0.00 | 0.00 | insufficient sample |
| learn2tradenews | 4 | -0.08 | -0.08 | 0.00 | insufficient sample |
| starxhuk_6273 | 1 | 0.00 | -0.07 | 0.00 | insufficient sample |
| unitedsignalsfx | 20 | -2.24 | -0.73 | 0.84 | unstable/negative |
| freeforexpipssignals | 2 | -0.37 | -0.13 | 0.00 | insufficient sample |
| nasgold1 | 6 | 0.44 | -0.78 | 0.51 | unstable/negative |
| signalprovider6 | 4 | 0.20 | -1.80 | 0.14 | insufficient sample |
| gold_signals | 11 | -4.14 | -2.97 | 0.16 | unstable/negative |
| tradewindonesia | 1 | 0.00 | -1.07 | 0.00 | insufficient sample |
| tradingpromoney | 1 | 0.00 | -1.08 | 0.00 | insufficient sample |
## Interpretation

No provider/filter/horizon combination selected on the earlier messages met the later-period gate. More cards or a longer hold did not create a robust edge from these sources.

This is research, not a production configuration change. Proxy/broker basis differences, Telegram parsing errors, deleted messages, and the short capture window remain material limitations.
