---
name: trading-session
description: Assisted FBS trading-session workflow for reading expert Telegram signals, validating them against current market data, scoring them, and reporting candidate setups. Use when the user asks to run a trading session, review Telegram trading signals, find FBS setups across forex/crypto/metals/indices/energies/stocks, or generate the daily trading-session Markdown report.
---

# Trading Session

## Workflow

Use this skill to produce a standardized daily shortlist of FBS trade candidates from expert Telegram channels. Do not execute orders. Treat the user as the only execution authority.

1. Load config from `config/sources.yaml` and `config/session-params.yaml` when present; otherwise use the matching `.example.yaml` defaults.
2. Load Telegram credentials from `.env.telegram` before running the session when that file exists. The runner does not auto-load dotenv files.
3. Run `scripts/run_telegram_fbs_session.py` for the session.
4. Read only enabled Telegram channels from the configurable source list.
5. Restrict candidates to configured FBS symbols across crypto CFDs, forex, metals, energies, indices, and stocks.
6. Keep only expert signals with FBS asset symbol, direction, entry, stop loss, at least one take profit, timestamp, source channel, and acceptable risk/reward.
7. Validate each candidate against current market data when a validator is configured. Crypto CFDs use Binance public data as a technical proxy; non-crypto signals without a configured validator must be shown as discarded until confirmed in FBS.
8. Score candidates from 1 to 5 stars. Prefer fresh, clear, close-to-entry expert signals with acceptable R/R, trusted channel priority, and verifiable market context.
9. Write `sessions/YYYY-MM-DD/session-report.md` with up to 5 candidates: 3 primary and 2 backup.

## Operational Command

For a normal new session, run from the repository root:

```bash
set -a; source .env.telegram; set +a; python3 skills/trading-session/scripts/run_telegram_fbs_session.py
```

If `.env.telegram` is missing, run the script anyway once and report the generated discard reason. If the report says `TELEGRAM_API_ID and TELEGRAM_API_HASH are required`, the session is blocked on credentials and no Telegram messages were reviewed.

The script requires network access for Telegram plus public market/regime validators such as Binance, Yahoo Finance proxies, and Alternative.me. If the first run fails with DNS, host resolution, connection, or API/network errors, retry the same command with escalated network permission instead of falling back to stale data.

After the command finishes, read `sessions/YYYY-MM-DD/session-report.md` and summarize:

- `Telegram messages reviewed`
- `Candidates reviewed`
- `Valid candidates`
- whether `Top Candidates` or `Backup Candidates` contain actionable setups
- the main discard reasons

## Analyst Overlay

Do not present a candidate as actionable only because it passed parser and risk/reward checks. Before summarizing any Top or Backup candidate to the user, apply an analyst overlay:

- Confirm the signal is still live relative to current price, original entry, SL, and first TP.
- Check whether the direction agrees with current market context where data is available: recent momentum, higher-timeframe bias, nearby support/resistance, volatility, and obvious overextension.
- Prefer clean continuation or pullback setups over late entries chasing a move into TP.
- Downgrade or withhold candidates when the expected move is already mostly consumed, when price is sitting near a major opposing level, or when the signal depends on unvalidated assumptions.
- Explain the final recommendation in plain language: why it is acceptable, why it is only a pullback/rupture setup, or why it should be skipped.

The automated report is a shortlist generator, not the final trading decision. The assistant must add this market-expectation review before telling the user a setup is good.

## FBS Crypto CFD Sessions

- Report the FBS symbol as `asset`.
- Keep the Binance `USDT` proxy symbol only in evidence or `source_context.market_symbol`.
- Use the execution labels `tomable ahora`, `solo con pullback`, `solo con ruptura`, and `descartada`.
- Supported setup types are `trend_continuation`, `pullback`, `breakout`, and `controlled_reversal`.
- Use closed candles only; do not generate a setup from the currently forming candle.
- Check trend context across `15m`, `1h`, and `4h`.
- Reject late entries in obviously overextended moves, especially when `1h` or `4h` RSI is extreme.
- Require acceptable liquidity, quote volume, spread proxy, and volume confirmation before considering an asset tradable.
- Use recent support/resistance or recent range context when placing SL and TP.
- Use the executable quote side for entries: `Ask` for `BUY`, `Bid` for `SELL`. Recalculate R/R from that executable entry, not only from the closed-candle signal price.
- Require a minimum acceptable R/R; prefer `1.6` or better.
- Do not calculate or present final FBS lot size from Binance spot data. For forex and metals only, show an indicative lot size when contract size and quote-currency conversion are available; still tell the user to confirm the value of point, spread, and margin in FBS before execution. Show `TBD` for markets whose FBS contract value is not modeled.
- It is acceptable to return fewer than 5 candidates, or even zero, when the market does not offer clean setups.

## Telegram FBS Sessions

- Telegram is the primary source of trade ideas; market data is only a validation layer.
- Channels are controlled in `config/sources.yaml` under `type: telegram_signals`; channels can be added, disabled, reprioritized, or scoped by market.
- Required Telegram credentials are `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and optionally `TELEGRAM_SESSION`; keep them in `.env`/`.env.telegram`, never in git.
- Parse text signals first. Treat images/charts as evidence when attached, but do not invent missing entry, SL, or TP from an image unless a future OCR/chart parser is explicitly added and tested.
- Mark signals as `vigente`, `llegada_tarde`, `vencida`, `duplicada`, `incompleta`, or `descartada`.
- Treat Telegram signals as hypotheses, not instructions. A signal can be recommended only after independent validation of market viability and source reliability.
- Validate trade structure before scoring: for `BUY`, require `SL < entry < TP`; for `SELL`, require `TP < entry < SL`.
- Reject signals whose first TP or SL has already been reached by current validated market price. Do not move targets to rescue an old signal.
- Prefer channels that repeatedly publish complete, timely, executable signals. Penalize or discard channels/messages that mostly publish marketing, hindsight wins, account-management ads, or partial screenshots without entry/SL/TP.
- Ranking must combine expert signal quality with current market reality: freshness, channel priority, R/R, entry distance, current bid/ask/proxy price, spread/liquidity where available, and whether the setup is still actionable now.
- If current price has moved too far from the expert entry, do not chase it. Keep the original signal and add `modification_note` explaining the wait-for-pullback condition.
- Signals outside the configured FBS universe must be discarded as `outside_fbs_universe`.
- The configured FBS universe is intentionally broad but not guaranteed exhaustive. FBS advertises 550+ CFD assets, including 470+ stock CFDs, so unknown but plausible stock/index symbols must be labeled `unknown_fbs_symbol` instead of assumed unavailable.
- Accept common stock notation such as `#AAPL`, `AAPL`, `COIN`, or company-name aliases when configured. Require market-data validation before promoting any stock signal to Top Candidates.
- Non-crypto FBS markets require a configured market-data validator before they can become top candidates. Otherwise include them in discarded signals with `market_data` missing and tell the user to confirm in FBS.

## Required Behavior

- Use `capital_usd: 100` and `max_risk_usd: 2` unless config overrides them. For forex and metals, calculate indicative lot sizing from entry-to-SL distance and known contract sizes; for other FBS markets, do not infer lot sizing without confirmed contract specs.
- Reject candidates without SL or TP.
- Reject candidates outside the configured signal window unless the user explicitly requests a wider session.
- Never invent market prices. If public market data is missing, mark the candidate discarded or abort if the session cannot be validated.
- Do not present Binance, CoinGecko, Alternative.me, or any market-data proxy as third-party trader signals.
- Do not include assets outside the configured FBS allowlist.
- Keep the report format stable across sessions. Read `references/session-output.md` before writing the report.

## Scripts

- `scripts/run_telegram_fbs_session.py`: run the Telegram-driven FBS session and write `sessions/YYYY-MM-DD/session-report.md`.
- `scripts/run_crypto_web_session.py`: legacy credential-free FBS crypto CFD session using public web data.
- `scripts/fetch_binance_market.py`: fetch Binance public market data and produce filtered setup candidates using closed candles, multi-timeframe trend, RSI, relative volume, spread proxy, liquidity, range context, and R/R checks.
- `scripts/score_candidates.py`: score normalized candidates and render a Markdown report from JSON input.
- `scripts/normalize_candidates.py`: normalize candidate JSON into the common report schema when needed.

Other legacy scripts may exist in the repository, but they are not part of this skill's supported workflow.

## Safety

This skill provides analysis only. Do not place, modify, or cancel live orders. Do not provide guarantees of profit. Make uncertainty visible in the report and prefer discarding ambiguous setups.
