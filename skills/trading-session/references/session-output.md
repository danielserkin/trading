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
- `Source` must be `telegram_signal` for the active Telegram/FBS workflow.
- `Provider` should be the Telegram channel id.
- `Asset` must be a configured FBS symbol, such as `BTCUSD`, `EURUSD`, or `XAUUSD`.
- `Entry` must be the executable side of the quote: `Ask` for `BUY`, `Bid` for `SELL`.
- `Current` should include `Bid / Ask` and spread when available, so the user can compare it with the trading platform before placing an order.
- `Risk USD` and `Size` must be `TBD` until FBS contract value and lot sizing are confirmed in the trading platform.
- `Volume Est.` may show estimated asset units from the public market proxy, but it is not the final FBS lot size.
- `Evidence` must summarize the Telegram message and any public proxy market data used for validation.
- `Why` must include vigencia/status and any `modification_note` when the expert entry is no longer directly actionable.

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

## Data Used

Include:

- Public sources consulted: Binance, CoinGecko, and Alternative.me.
- Broker universe: FBS.
- FBS crypto CFD symbols allowed.
- Symbols scanned and session params used.
