---
name: active-trade-manager
description: Review current FBS positions from screenshots attached in chat or recent files, reconnect them to their original local signals, recommend exact hold/close/partial-close/SL/TP actions, and notify the configured Telegram channel. Use when the user says revision, revisión, revisar, or otherwise requests active/open trade management; do not use for completed-session outcome reviews or new trade discovery.
---

# Active Trade Manager

Review open positions and give one executable management decision per ticket. Optimize protected expectancy rather than raw win rate. Never place, modify, or close an order.

Read [references/management-policy.md](references/management-policy.md) before analyzing a position.

## Workflow

1. Determine the current screenshot batch from either source:
   - Images attached to the triggering chat request are current evidence even when they are not saved under `active-trades/`. Inspect them directly and never require the user to copy them into the workspace.
   - Also find PNG, JPG, JPEG, or WebP files under `active-trades/`, sorted by modification time. Treat files modified within 15 minutes as current.
   When both sources contain the same ticket, use the image showing the latest platform state. Do not let an older workspace file override a fresh chat attachment. If neither source provides current evidence, ask for a new screenshot and do not present old prices as actionable.
2. Inspect every image in the current batch, including every relevant chat attachment. Extract ticket, asset, direction, volume, entry, current executable price, profit, SL, TP, chart timeframe, visible structure, and platform/server time. State any unreadable field.
3. Match each position to `sessions/*/telegram-fbs-candidates.json`, `session-report.md`, and `sessions/idea-ledger.json` using asset, direction, entry, time, and idea ID when available. Prefer an exact entry match. Keep unmatched positions clearly labeled instead of inventing signal context.
4. Verify current market context and imminent high-impact events using fresh sources when available. The FBS screenshot is authoritative for the position and executable broker quote; public proxies are supporting evidence only. Never substitute stale proxy prices.
5. Calculate progress toward TP, current result in pips and R when possible, remaining reward, risk to the current SL, visible favorable excursion, pullback, age, validity, rollover, overnight, news, and weekend exposure.
6. Select exactly one primary action per ticket from `MANTENER`, `MOVER_SL`, `AJUSTAR_TP`, `CIERRE_PARCIAL`, `CERRAR_TODO`, or `EVIDENCIA_INSUFICIENTE`. Give exact values and volume for every requested modification.
7. Present the decision in Spanish, then publish the same decision to Telegram with `scripts/publish_active_trade_action.py`. Load `.env.telegram` without printing its contents. Use one consolidated payload for all tickets. If delivery fails, preserve the recommendation and report the failure; never retry more than once after a transient network failure.

## Telegram invocation

Build the validated payload described in the policy reference and run:

```bash
set -a; source .env.telegram; set +a
python3 skills/active-trade-manager/scripts/publish_active_trade_action.py --payload-json '<json>'
```

Use `--dry-run` during testing. Do not write a local management report or expose tokens, chat IDs, account numbers, or passwords.

## Boundaries

- For a BUY, use Bid as the approximate market-close price; for a SELL, use Ask.
- Never widen an SL, increase initial risk, move a TP farther merely to chase profit, average down, or recommend re-entry.
- Do not promise more winners. Explain when protecting profit reduces remaining upside.
- If a partial close is appropriate but the broker's lot step is unknown, choose a safe simple action instead of inventing a volume.
- Keep the original signal analysis distinct from new information and label hindsight explicitly.
