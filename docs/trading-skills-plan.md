# Trading Skill Scope

## Current Supported Workflow

The active trading-session workflow is Telegram-driven FBS signal validation.

- Primary source: enabled Telegram expert-signal channels from `config/sources.yaml`.
- Broker universe: configurable FBS allowlist across crypto CFDs, forex, metals, energies, indices, and stocks.
- Crypto market-data proxy: Binance public spot data for matching crypto/USD assets.
- Non-crypto market-data validation: must be configured before signals can become top candidates.
- Regime context: Alternative.me Fear & Greed.
- Output: `sessions/YYYY-MM-DD/session-report.md`.
- Mode: recommendation only; no order execution.

## Safety

FBS lot sizing and CFD contract value must be confirmed in the FBS platform before execution. The report must show `Risk USD` and `Size` as `TBD` for FBS candidates until that data is available from the broker.

Telegram credentials and session files are local secrets and must not be committed.
