---
name: trading-session
description: Run an assisted FBS trading session that seeks three analyzed, distinct trade options by validating Telegram signals, recalculating re-entries/reversals, and scanning the modeled FBS universe when coverage is short. Render the daily report and publish its summary to Telegram. Use immediately when the user says "nueva sesión", "nueva session", "iniciar sesión de trading", or otherwise asks for a new trading session, FBS signal review, Telegram delivery setup, or daily candidate report. Treat those short phrases as commands to run the workflow, not as greetings or requests for clarification. Never execute orders.
---

# Trading Session

## Run a session

1. Read `references/session-output.md` before interpreting or changing report fields.
2. Load `config/sources.yaml` and `config/session-params.yaml`; fall back to their `.example.yaml` files.
3. Load secrets and install declared dependencies when needed:

```bash
set -a; source .env.telegram; set +a
python3 -c "import telethon" || python3 -m pip install --user -r skills/trading-session/requirements.txt
python3 skills/trading-session/scripts/run_telegram_fbs_session.py
```

4. The runner always requires live network access for Telegram and current market data. If the execution environment sandboxes network access, request network permission on the initial runner invocation; do not perform an expected-to-fail offline attempt. If an already network-enabled invocation fails transiently, retry the same command. Never fall back to stale prices.
5. Read `sessions/YYYY-MM-DD/session-report.md` and verify each candidate against its current price, SL, TP, trigger, higher-timeframe context, and overextension checks.
6. Summarize messages reviewed, candidates reviewed, valid candidates, the three evaluated slots, backups, primary discard reasons, and Telegram delivery status.

The runner performs preflight before writing output. A missing `Telethon` installation or missing reader credentials must stop the session with an actionable error.

## Configure Telegram delivery

Keep all credentials in `.env.telegram`, never in Git. Copy variable names from `.env.telegram.example`.

1. Create a bot with `@BotFather` and keep its token private.
2. Create a private channel and add the bot as an administrator with permission to post.
3. Publish one channel message after adding the bot.
4. Load `.env.telegram` with `TELEGRAM_BOT_TOKEN`, then discover the channel ID:

```bash
set -a; source .env.telegram; set +a
python3 skills/trading-session/scripts/publish_telegram_summary.py --discover
```

5. Save the returned negative channel ID as `TELEGRAM_TARGET_CHAT_ID` and test it:

```bash
set -a; source .env.telegram; set +a
python3 skills/trading-session/scripts/publish_telegram_summary.py --test
```

When both bot variables exist, every successful runner invocation publishes a new compact summary. A delivery failure preserves the report and returns a nonzero status. Do not expose the bot token in output.

## Candidate policy

- Treat Telegram as the first idea source. When it cannot supply three clean assets, market APIs may originate independently labeled technical setups from closed candles; never attribute those setups to an expert.
- Accept an original signal only with recognized FBS asset, direction, entry, SL, TP, acceptable R/R, fresh market data, and a live path between SL and TP.
- Reject a signal already at SL/TP, too close to SL, mostly consumed toward TP, stale, structurally invalid, or dependent on an unconfirmed proxy.
- Use Binance Ask for crypto BUY and Bid for crypto SELL. For Yahoo-backed markets, require confirmation of executable Bid/Ask and spread in FBS.
- Use USD 1,000 reference capital, USD 20 maximum risk per unique idea, and minimum R/R 1.6 unless local config overrides them.
- Show indicative lot size only for modeled contracts. Confirm point value, spread, margin, and contract specification in FBS. Use `TBD` otherwise and reject candidates whose risk cannot be calculated.
- The user executes mechanically from Telegram and does not inspect candles. Resolve all technical confirmation before publishing and specify `BUY STOP`, `BUY LIMIT`, `SELL STOP`, or `SELL LIMIT` explicitly.
- Include the exact entry, SL, TP, lot size, risk, and expiry. Because the proxy may differ from FBS Bid/Ask, allow switching STOP/LIMIT within the same direction only when FBS requires it for the exact same entry; never change the levels or lot.

## Fallback opportunities

When fewer than three original candidates survive, run `scripts/derive_opportunities.py` through the main runner and exhaust the configured coverage layers:

- First use recognizable expert seeds from the configured fallback window and recalculate all levels from current closed-candle data.
- Require closed `15m`, `1h`, and `4h` candles, aligned higher timeframes, controlled RSI, ATR-based structure, and volume confirmation when available.
- If seeded opportunities remain insufficient, scan configured FBS assets whose risk and lot size can be modeled. Evaluate continuation, pullback, breakout, and conditional-confirmation structures. A conditional setup must require activation through its exact pending-order trigger.
- Recalculate pending entry, order type, SL, TP, R/R, and setup-specific validity from closed-candle data before publishing.
- Label same-direction ideas `reentry` and opposite-direction ideas `technical_reversal`. Never attribute a reversal to the expert channel.
- Label independent scanner ideas `market_scan` with their public provider and complete technical evidence.
- Produce at most one primary setup per asset and select three different assets. Prefer three valid options on every execution, while preserving the configured R/R, risk, freshness, structure, overextension, and sizing requirements.
- Fill a remaining primary slot with `NO TRADE` only after all configured sources, re-entry seeds, and modeled scan assets are exhausted. Record the scan count and missing confirmation; never invent levels or publish random filler.

## Output and safety

Write stable latest-snapshot artifacts under `sessions/YYYY-MM-DD/`: candidates JSON, metadata JSON, Markdown report, and Telegram delivery status. Also preserve every invocation under `sessions/YYYY-MM-DD/runs/<run-id>/` when run history is enabled. Keep three evaluated primary slots plus up to two backups.

Treat the dated root files as the latest snapshot; another run on the same day replaces them without deleting the immutable per-run copy. Configured Telegram delivery publishes a new channel message for every run.

Provide analysis only. Do not place, modify, or cancel live orders. Do not promise profit or invent missing prices, levels, evidence, or broker specifications.
