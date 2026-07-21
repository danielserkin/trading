# Trading Skill Scope

## Current Supported Workflow

The active trading-session workflow is limited to FBS crypto CFD setup discovery.

- Broker universe: FBS crypto CFDs only.
- Candidate symbols: `BCHUSD`, `BTCUSD`, `ETHUSD`, `LTCUSD`, `XRPUSD`, `TRXUSD`, `DOGUSD`, `SOLUSD`, `XLMUSD`, `BNBUSD`, `ETCUSD`, `ADAUSD`, `DOTUSD`.
- Market-data proxy: Binance public spot data for matching crypto/USD assets.
- Universe/context: CoinGecko public market data.
- Regime context: Alternative.me Fear & Greed.
- Output: `sessions/YYYY-MM-DD/session-report.md`.
- Mode: recommendation only; no order execution.

## Safety

FBS lot sizing and CFD contract value must be confirmed in the FBS platform before execution. The report must show `Risk USD` and `Size` as `TBD` for FBS candidates until that data is available from the broker.
