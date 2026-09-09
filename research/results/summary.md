# Signal research decision — 2026-09-09

## Decision

Do not loosen the current intraday filters merely to create trades. None of the
frequent-signal approaches survived chronological validation with costs. The
only model that passed the predeclared research gate was a slow monthly FX carry
model. It is eligible for a separate demo forward test, not for an immediate
replacement of the live scanner.

## Comparable results

| Test | Data and validation | Validation result | Decision |
|---|---|---:|---|
| Static intraday price signals | Dukascopy M15, 4 pairs, final 30% untouched | -23.16R, PF 0.39 | Reject |
| Adaptive recent-winner selection | Dukascopy M15, nested final 30% | -24.36R, PF 0.44 | Reject |
| Current Telegram providers | Yahoo M15 proxy, Aug 19–27 untouched | -2.21R at 12h, PF 0.67 | Reject |
| Intraday currency strength | Yahoo H1, 15 pairs, final 30% | -8.17R, PF 0.89 | Reject |
| Swing currency strength | Yahoo D1, 15 pairs, final 30% | +1.79R, PF 1.09 | Below gate |
| Monthly carry | Yahoo D1 + lagged OECD/FRED rates, final 30% | +10.73R, PF 1.88 | Demo candidate |
| Intraday carry filter | Yahoo H1 + lagged OECD/FRED rates, final 30% | +3.61R, PF 1.05; -11.98R at 2x costs | Reject |

## Monthly carry candidate

- Universe: 15 FX pairs built from USD, EUR, GBP, JPY, CHF, CAD, AUD and NZD.
- Signal time: first available trading day of the month.
- Information rule: latest OECD/FRED rate observation with a conservative
  45-day publication lag.
- Rank: highest absolute base/quote rate differential, minimum 1 percentage
  point; buy the higher-rate currency and sell the lower-rate currency.
- Capacity: one position. The directly expanded three-card version was positive
  in validation but weak in training (PF 1.03), so it is not approved.
- Execution proxy: next daily open.
- Stop: 1.5 × daily ATR(14).
- Target: 1.0R.
- Time exit: 20 trading days.
- Validation: 37 fills, 24 positive, +10.73R, average +0.290R, PF 1.88,
  max drawdown 3.03R.
- Double-cost validation: +10.39R, PF 1.84.
- Neighborhood: 16/16 nearby parameter variants positive in validation.
- Concentration check: all eight leave-one-currency-out cases stayed positive.
- Statistical caveat: bootstrap 95% interval for mean R is [-0.0168, 0.5755],
  so the sample still does not prove a positive population mean.

## What this means for the three cards

The platform may retain capacity for three cards, but the validated model should
populate only one. Filling the other two without an independent edge reduced
quality and increased drawdown. “Up to three” must not become “three required.”

## Required next phase

1. Implement the carry model as an isolated demo-only module, leaving the current
   intraday scanner unchanged and clearly labeling its monthly cadence.
2. Verify the selected pair's actual FBS long/short swap before publishing a
   card; the backtest deliberately did not assume interbank carry equals broker
   CFD swap.
3. Record broker bid/ask, spread, fill and swap for every candidate and no-fill.
4. Keep intraday research separate until there are at least 90 days of true
   point-in-time broker candles plus economic-calendar surprises or order-flow
   data. More price-indicator permutations are not justified by these results.

## Reproducible artifacts

- `forex-independent-dukascopy/`: independent rejection of the first Yahoo winner.
- `forex-dukascopy-walk-forward/`: static nine-family search on Dukascopy.
- `forex-adaptive-nested/`: nested adaptive selector and hindsight-only ceiling.
- `telegram-provider-walk-forward/`: deduplicated historical provider signals.
- `forex-currency-strength/`: frequent hourly cross-sectional signals.
- `forex-currency-strength-swing/`: daily/weekly/monthly price-strength variants.
- `forex-carry/`: passing monthly macro candidate and robustness diagnostics.
- `forex-intraday-carry/`: failed high-frequency macro-conditioned variant.
