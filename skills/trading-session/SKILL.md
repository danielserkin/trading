---
name: trading-session
description: Run an assisted FBS trading session from configured Telegram expert channels, validate signals with current market data, derive conditional re-entry or reversal opportunities when fewer than three clean signals exist, render the daily report, and publish its summary to Telegram. Use immediately when the user says "nueva sesión", "nueva session", "iniciar sesión de trading", or otherwise asks for a new trading session, FBS signal review, Telegram delivery setup, or daily candidate report. Treat those short phrases as commands to run the workflow, not as greetings or requests for clarification. Never execute orders.
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

4. If network access fails, retry the same command with network permission. Never fall back to stale prices.
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

- Treat Telegram as the idea source and market APIs only as validation evidence.
- Accept an original signal only with recognized FBS asset, direction, entry, SL, TP, acceptable R/R, fresh market data, and a live path between SL and TP.
- Reject a signal already at SL/TP, too close to SL, mostly consumed toward TP, stale, structurally invalid, or dependent on an unconfirmed proxy.
- Use Binance Ask for crypto BUY and Bid for crypto SELL. For Yahoo-backed markets, require confirmation of executable Bid/Ask and spread in FBS.
- Use USD 1,000 reference capital, USD 20 maximum risk per unique idea, and minimum R/R 1.6 unless local config overrides them.
- Show indicative lot size only for modeled contracts. Confirm point value, spread, margin, and contract specification in FBS. Use `TBD` otherwise and reject candidates whose risk cannot be calculated.
- The user executes mechanically from Telegram and does not inspect candles. Resolve all technical confirmation before publishing and specify `BUY STOP`, `BUY LIMIT`, `SELL STOP`, or `SELL LIMIT` explicitly.
- Include the exact entry, SL, TP, lot size, risk, and expiry. Because the proxy may differ from FBS Bid/Ask, allow switching STOP/LIMIT within the same direction only when FBS requires it for the exact same entry; never change the levels or lot.

## Fallback opportunities

When fewer than three original candidates survive, run `scripts/derive_opportunities.py` through the main runner:

- Use only recognizable expert seeds from the configured 72-hour fallback window.
- Require closed `15m`, `1h`, and `4h` candles, aligned higher timeframes, controlled RSI, ATR-based structure, and volume confirmation when available.
- Recalculate pending entry, order type, SL, TP, R/R, and two-hour validity from closed-candle data before publishing.
- Label same-direction ideas `reentry` and opposite-direction ideas `technical_reversal`. Never attribute a reversal to the expert channel.
- Produce at most one derived setup per asset.
- Fill any remaining primary slots with `NO TRADE` and the missing confirmation. Never weaken thresholds merely to force three trades.

## Output and safety

Write stable artifacts under `sessions/YYYY-MM-DD/`: candidates JSON, metadata JSON, Markdown report, and Telegram delivery status. Keep three evaluated primary slots plus up to two backups.

Treat the dated files as the latest snapshot: another run on the same day replaces them, while configured Telegram delivery publishes a new channel message for every run.

Provide analysis only. Do not place, modify, or cancel live orders. Do not promise profit or invent missing prices, levels, evidence, or broker specifications.
