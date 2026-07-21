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

| Rank | Stars | Source | Provider | Asset | Direction | Entry | Current | SL | TP | R/R | Risk USD | Size | Valid Until | Evidence | Why |

Rules:

- `Stars` must be one to five literal `*` characters.
- `Source` must be `binance_market` for the active FBS crypto CFD workflow.
- `Asset` must be an FBS crypto CFD symbol, such as `BTCUSD` or `SOLUSD`, not the Binance proxy symbol.
- `Risk USD` and `Size` must be `TBD` until FBS contract value and lot sizing are confirmed in the trading platform.
- `Evidence` must summarize the scanner condition, public proxy market data, FBS broker context, and any regime context used.
- `Why` must be one concise reason, not a long paragraph.

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
