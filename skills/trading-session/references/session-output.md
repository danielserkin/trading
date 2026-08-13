# Trading Session Report Format

Write the daily report to:

`sessions/YYYY-MM-DD/session-report.md`

Use this exact section order:

1. `# Trading Session - YYYY-MM-DD`
2. `## Summary`
3. `## Top Candidates`
4. `## Backup Candidates`
5. `## Discarded Signals`
6. `## Data Used`
7. `## Notes`

## Candidate Columns

Use the same columns for primary and backup tables:

| Rank | Stars | Source | Provider | Asset | Direction | Entry | Current | SL | TP | R/R | Risk USD | Size | Volume Est. | Valid Until | Evidence | Why |

Rules:

- `Stars` must be one to five literal `*` characters.
- `Source` must be `telegram_signal` for original expert signals or `telegram_derived` for independently recalculated re-entry/reversal setups.
- `Provider` should be the Telegram channel id.
- `Asset` must be a configured FBS symbol, such as `BTCUSD`, `EURUSD`, or `XAUUSD`.
- `Entry` must be the executable side of the quote: `Ask` for `BUY`, `Bid` for `SELL`.
- `Current` should include `Bid / Ask` and spread when available, so the user can compare it with the trading platform before placing an order.
- `Risk USD` and `Size` may show indicative FBS lot sizing for forex and metals when contract size and quote-currency conversion are available. Use `TBD` for markets whose FBS contract value is not modeled.
- `Volume Est.` may show estimated lots and TP1 profit for forex/metals, or estimated asset units from a public market proxy. It is still an estimate that must be confirmed in FBS.
- `Evidence` must summarize the Telegram message and any public proxy market data used for validation.
- `Why` must include vigencia/status and any `modification_note` when the expert entry is no longer directly actionable.
- `Why` must state the pending-order type and exact mechanical instruction; it must not delegate candle analysis to the user.
- Derived rows must identify `reentry` or `technical_reversal`, include the pending order and expiry/cancellation rule, and link back to the seed message when available.
- Always show three evaluated primary slots. Use a `NO TRADE` row when evidence is insufficient; do not represent it as a valid candidate.

## Discarded Signals

Use this table:

| Source | Provider | Raw Asset | Direction | Reason |

Allowed reasons include:

- `missing_sl`
- `missing_tp`
- `outside_window`
- `symbol_unavailable`
- `stale_market_data`
- `entry_too_far`
- `spread_too_high`
- `risk_above_limit`
- `parse_uncertain`
- `too_close_to_stop`
- `move_mostly_consumed`
- `higher_timeframes_not_aligned`
- `volume_confirmation_missing`

## Data Used

Include:

- Public sources consulted: Binance, CoinGecko, and Alternative.me.
- Broker universe: FBS.
- FBS crypto CFD symbols allowed.
- Symbols scanned and session params used.
- Fallback attempts, accepted derived setups, rejection reasons, and `NO TRADE` slot count.
- Telegram delivery status is written separately to `telegram-delivery.json`.
