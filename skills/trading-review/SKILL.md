---
name: trading-review
description: Post-session review workflow for assisted trading sessions. Use when the user reports what happened after taking recommended trades, wants to evaluate wins/losses/no-fills, update local channel or setup metrics, compare outcomes against the trading-session report, or refine future scoring and filters.
---

# Trading Review

## Workflow

Use this skill after the user finishes or abandons a trading session. The goal is to learn from outcomes and improve future sessions without rewriting rules automatically.

1. Locate the session folder, usually `sessions/YYYY-MM-DD/`.
2. Read `session-report.md` and identify the recommended top and backup candidates.
3. Ask the user only for missing outcome facts that cannot be inferred: which trades were entered, entry price, exit/result, whether SL/TP hit, manual close reason, and execution notes.
4. Normalize each outcome as `win`, `loss`, `breakeven`, `not_executed`, `missed`, or `manual_close`.
5. Write `sessions/YYYY-MM-DD/review.md` using `references/review-output.md`.
6. Update local metrics from the review input when enough structured data is available.
7. Propose concrete changes to `config/session-params.yaml` or channel inclusion rules, but do not apply them unless the user asks.

## Review Rules

- Keep analysis tied to the original report. Do not judge a trade using information that was unavailable at session time without labeling it as hindsight.
- Separate signal quality from execution quality.
- Track no-fill and missed-trade cases; they matter for channel usefulness.
- Prefer small parameter changes based on repeated evidence, not one outcome.
- Preserve original session reports. Write a new review file instead of editing the report.

## Scripts

- `scripts/render_review.py`: render a stable Markdown review from structured JSON outcomes.

Use scripts for repeatable formatting. Use judgment for improvement proposals.
