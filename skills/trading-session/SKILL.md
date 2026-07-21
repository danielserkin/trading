---
name: trading-session
description: Assisted FBS crypto CFD trading-session workflow for finding, validating, scoring, and reporting candidate setups using public web market data. Use when the user asks to run a trading session, find FBS crypto CFD setups, shortlist crypto trades, validate setups with current market data, or generate the daily trading-session Markdown report.
---

# Trading Session

## Workflow

Use this skill to produce a standardized daily shortlist of FBS crypto CFD trade candidates. Do not execute orders. Treat the user as the only execution authority.

1. Load config from `config/sources.yaml` and `config/session-params.yaml` when present; otherwise use the matching `.example.yaml` defaults.
2. Run `scripts/run_crypto_web_session.py` for the session.
3. Restrict candidates to FBS-offered crypto CFD symbols only: `BCHUSD`, `BTCUSD`, `ETHUSD`, `LTCUSD`, `XRPUSD`, `TRXUSD`, `DOGUSD`, `SOLUSD`, `XLMUSD`, `BNBUSD`, `ETCUSD`, `ADAUSD`, and `DOTUSD`.
4. Use Binance public market data only as a technical proxy for matching crypto/USD symbols, CoinGecko only for universe/liquidity/momentum context, and Alternative.me only for broad crypto regime context.
5. Keep only candidates with FBS asset symbol, direction, entry, stop loss, at least one take profit, current price proxy, and acceptable risk/reward.
6. Validate each candidate against closed candles, multi-timeframe trend, liquidity, spread proxy, volume participation, recent range context, and R/R.
7. Score candidates from 1 to 5 stars. Prefer fresh, clear, close-to-entry setups with acceptable R/R and strong technical quality.
8. Write `sessions/YYYY-MM-DD/session-report.md` with up to 5 candidates: 3 primary and 2 backup.

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
- Require a minimum acceptable R/R; prefer `1.6` or better.
- Do not calculate or present final FBS lot size from Binance spot data. Show `Risk USD` and `Size` as `TBD` until FBS contract value and lot sizing are confirmed in the trading platform.
- It is acceptable to return fewer than 5 candidates, or even zero, when the market does not offer clean setups.

## Required Behavior

- Use `capital_usd: 100` and `max_risk_usd: 2` unless config overrides them, but do not infer FBS lot sizing from those values.
- Reject candidates without SL or TP.
- Reject candidates outside the intraday window unless the user explicitly requests a wider session.
- Never invent market prices. If public market data is missing, mark the candidate discarded or abort if the session cannot be validated.
- Do not present Binance, CoinGecko, or Alternative.me data as third-party trader signals.
- Do not include assets outside the FBS crypto CFD allowlist.
- Keep the report format stable across sessions. Read `references/session-output.md` before writing the report.

## Scripts

- `scripts/run_crypto_web_session.py`: run the credential-free FBS crypto CFD session using public web data and write `sessions/YYYY-MM-DD/session-report.md`.
- `scripts/fetch_binance_market.py`: fetch Binance public market data and produce filtered setup candidates using closed candles, multi-timeframe trend, RSI, relative volume, spread proxy, liquidity, range context, and R/R checks.
- `scripts/score_candidates.py`: score normalized candidates and render a Markdown report from JSON input.
- `scripts/normalize_candidates.py`: normalize candidate JSON into the common report schema when needed.

Other legacy scripts may exist in the repository, but they are not part of this skill's supported workflow.

## Safety

This skill provides analysis only. Do not place, modify, or cancel live orders. Do not provide guarantees of profit. Make uncertainty visible in the report and prefer discarding ambiguous setups.
