# Trading Review Output Format

Write the review to:

`sessions/YYYY-MM-DD/review.md`

Use this exact section order:

1. `# Trading Review - YYYY-MM-DD`
2. `## Outcome Summary`
3. `## Trades Reviewed`
4. `## Signal Quality`
5. `## Execution Notes`
6. `## Suggested Adjustments`
7. `## Next Session Defaults`

## Trades Reviewed Columns

| Rank | Asset | Direction | Planned Entry | Actual Entry | Exit/Result | Outcome | PnL USD | Notes |

Outcome values:

- `win`
- `loss`
- `breakeven`
- `not_executed`
- `missed`
- `manual_close`

## Suggested Adjustments

Group suggestions as:

- Channel filters
- Symbol filters
- Scoring weights
- Execution timing
- Risk settings

Do not modify config files unless the user explicitly asks.
