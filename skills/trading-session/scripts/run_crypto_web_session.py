#!/usr/bin/env python3
"""Run a public-web crypto spot session.

This runner uses only public data:
- CoinGecko for the broad asset universe and market context.
- Binance Spot public endpoints for executable USDT market validation.
- Alternative.me Fear & Greed for broad crypto regime context.
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fetch_binance_market import build_candidate, get_json as binance_get_json
from score_candidates import render_report


COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
ALTERNATIVE_ME_BASE_URL = "https://api.alternative.me"
DEFAULT_TOP_ASSETS = 80
DEFAULT_SYMBOLS = [
    "BTCUSD",
    "ETHUSD",
    "BNBUSD",
    "SOLUSD",
    "XRPUSD",
    "ADAUSD",
    "DOGUSD",
    "TRXUSD",
    "DOTUSD",
    "LTCUSD",
]
STABLE_SYMBOLS = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "USDS", "PYUSD", "BUSD", "USD1"}
FBS_CRYPTO_SYMBOL_MAP = {
    "BCHUSD": "BCHUSDT",
    "BTCUSD": "BTCUSDT",
    "ETHUSD": "ETHUSDT",
    "LTCUSD": "LTCUSDT",
    "XRPUSD": "XRPUSDT",
    "TRXUSD": "TRXUSDT",
    "DOGUSD": "DOGEUSDT",
    "SOLUSD": "SOLUSDT",
    "XLMUSD": "XLMUSDT",
    "BNBUSD": "BNBUSDT",
    "ETCUSD": "ETCUSDT",
    "ADAUSD": "ADAUSDT",
    "DOTUSD": "DOTUSDT",
}


def asset_unit(asset: str) -> str:
    upper = asset.upper()
    for suffix in ("USDT", "USD"):
        if upper.endswith(suffix):
            return upper.removesuffix(suffix)
    return upper


def enrich_candidate(candidate: dict[str, Any], capital_usd: float, max_risk_usd: float, valid_hours: int) -> dict[str, Any]:
    entry = float(candidate["entry"])
    stop_loss = float(candidate["stop_loss"])
    risk_per_unit = abs(entry - stop_loss)
    if risk_per_unit <= 0:
        candidate["risk_usd"] = None
        candidate["size"] = "TBD"
        return candidate

    capital_size = capital_usd / entry
    risk_limited_size = max_risk_usd / risk_per_unit
    size = min(capital_size, risk_limited_size)
    risk_usd = size * risk_per_unit

    candidate["risk_usd"] = round(risk_usd, 4)
    candidate["size"] = round(size, 8)
    candidate["volume_estimate"] = {
        "units": round(size, 8),
        "unit": asset_unit(str(candidate.get("asset", ""))),
        "notional_usd": round(size * entry, 4),
        "risk_usd": round(risk_usd, 4),
        "basis": "proxy_units",
    }
    candidate["valid_until"] = (datetime.now(timezone.utc) + timedelta(hours=valid_hours)).isoformat()
    return candidate


def get_public_json(base_url: str, path: str, params: dict[str, Any] | None = None) -> Any:
    query = urllib.parse.urlencode(params or {})
    url = f"{base_url}{path}"
    if query:
        url = f"{url}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "trading-session/1.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def load_simple_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
    except Exception:
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return data if isinstance(data, dict) else {}


def session_params(config_dir: Path) -> dict[str, Any]:
    params = load_simple_yaml(config_dir / "session-params.yaml")
    example = load_simple_yaml(config_dir / "session-params.example.yaml")
    merged = {
        "capital_usd": 100.0,
        "max_risk_usd": 2.0,
        "signal_window_hours": 24,
        "max_final_candidates": 5,
    }
    merged.update({k: v for k, v in example.items() if k in merged})
    merged.update({k: v for k, v in params.items() if k in merged})
    return merged


def binance_source_config(config_dir: Path) -> dict[str, Any]:
    config = load_simple_yaml(config_dir / "sources.yaml") or load_simple_yaml(config_dir / "sources.example.yaml")
    for source in config.get("sources", []):
        if isinstance(source, dict) and source.get("type") == "binance_market":
            return source
    return {}


def source_config(config_dir: Path, source_type: str) -> dict[str, Any]:
    config = load_simple_yaml(config_dir / "sources.yaml") or load_simple_yaml(config_dir / "sources.example.yaml")
    for source in config.get("sources", []):
        if isinstance(source, dict) and source.get("type") == source_type:
            return source
    return {}


def fetch_coingecko_markets(limit: int) -> list[dict[str, Any]]:
    per_page = min(max(limit, 1), 250)
    data = get_public_json(
        COINGECKO_BASE_URL,
        "/coins/markets",
        {
            "vs_currency": "usd",
            "order": "volume_desc",
            "per_page": per_page,
            "page": 1,
            "price_change_percentage": "1h,24h,7d",
            "sparkline": "false",
        },
    )
    return data if isinstance(data, list) else []


def fetch_fear_greed() -> dict[str, Any]:
    data = get_public_json(ALTERNATIVE_ME_BASE_URL, "/fng/", {"limit": 1, "format": "json"})
    rows = data.get("data", []) if isinstance(data, dict) else []
    latest = rows[0] if rows else {}
    value = int(latest.get("value") or 50)
    classification = str(latest.get("value_classification") or "Neutral")
    return {
        "value": value,
        "classification": classification,
        "regime": classify_regime(value, classification),
        "timestamp": latest.get("timestamp"),
    }


def classify_regime(value: int, classification: str) -> str:
    label = classification.lower()
    if value >= 75 or "extreme greed" in label:
        return "extreme_greed"
    if value >= 55 or "greed" in label:
        return "risk_on"
    if value <= 25 or "extreme fear" in label:
        return "extreme_fear"
    if value <= 45 or "fear" in label:
        return "risk_off"
    return "neutral"


def fetch_binance_usdt_symbols() -> set[str]:
    info = binance_get_json("/api/v3/exchangeInfo", {"symbolStatus": "TRADING"})
    symbols = set()
    for item in info.get("symbols", []):
        if item.get("status") != "TRADING":
            continue
        if item.get("quoteAsset") != "USDT":
            continue
        if "SPOT" not in item.get("permissions", []) and not any("SPOT" in permissions for permissions in item.get("permissionSets", [])):
            continue
        symbols.add(str(item.get("symbol", "")).upper())
    return symbols


def broker_symbol_map(config_dir: Path, broker: str) -> dict[str, str]:
    if broker.lower() != "fbs":
        return {}
    fbs_config = source_config(config_dir, "fbs_crypto_cfd")
    binance_config = binance_source_config(config_dir)
    configured = fbs_config.get("broker_symbol_map") or binance_config.get("broker_symbol_map")
    if isinstance(configured, dict):
        return {str(key).upper(): str(value).upper() for key, value in configured.items()}
    configured_symbols = fbs_config.get("broker_symbols") or binance_config.get("broker_symbols")
    if isinstance(configured_symbols, list) and configured_symbols:
        return {symbol: market for symbol, market in FBS_CRYPTO_SYMBOL_MAP.items() if symbol in {str(item).upper() for item in configured_symbols}}
    return dict(FBS_CRYPTO_SYMBOL_MAP)


def normalize_requested_symbol(symbol: str, allowed_broker_symbols: dict[str, str], allowed_market_symbols: set[str]) -> tuple[str, str] | None:
    upper = symbol.upper()
    if upper in allowed_broker_symbols:
        return upper, allowed_broker_symbols[upper]
    if upper in allowed_market_symbols:
        for broker_symbol, market_symbol in allowed_broker_symbols.items():
            if market_symbol == upper:
                return broker_symbol, market_symbol
    return None


def build_universe(config_dir: Path, top_assets: int, extra_symbols: list[str], broker: str) -> tuple[list[str], dict[str, dict[str, Any]], dict[str, Any]]:
    markets = fetch_coingecko_markets(top_assets)
    binance_symbols = fetch_binance_usdt_symbols()
    allowed_broker_symbols = broker_symbol_map(config_dir, broker)
    allowed_market_symbols = set(allowed_broker_symbols.values()) if allowed_broker_symbols else binance_symbols
    broker_by_market_symbol = {market: broker_symbol for broker_symbol, market in allowed_broker_symbols.items()}
    context_by_symbol: dict[str, dict[str, Any]] = {}
    symbols: list[str] = []

    for rank, coin in enumerate(markets, start=1):
        symbol = str(coin.get("symbol") or "").upper()
        if not symbol or symbol in STABLE_SYMBOLS:
            continue
        binance_symbol = f"{symbol}USDT"
        if binance_symbol not in binance_symbols:
            continue
        if binance_symbol not in allowed_market_symbols:
            continue
        if binance_symbol not in symbols:
            symbols.append(binance_symbol)
        context_by_symbol[binance_symbol] = {
            "broker": broker,
            "broker_symbol": broker_by_market_symbol.get(binance_symbol, binance_symbol),
            "market_symbol": binance_symbol,
            "coingecko_id": coin.get("id"),
            "coingecko_rank": coin.get("market_cap_rank") or rank,
            "liquidity_rank": rank,
            "total_volume": coin.get("total_volume"),
            "market_cap": coin.get("market_cap"),
            "price_change_1h": coin.get("price_change_percentage_1h_in_currency"),
            "price_change_24h": coin.get("price_change_percentage_24h_in_currency") or coin.get("price_change_percentage_24h"),
            "price_change_7d": coin.get("price_change_percentage_7d_in_currency"),
        }

    source_config = binance_source_config(config_dir)
    configured = [str(item).upper() for item in source_config.get("symbols", []) if item]
    for symbol in [*configured, *extra_symbols, *DEFAULT_SYMBOLS]:
        normalized = normalize_requested_symbol(symbol, allowed_broker_symbols, allowed_market_symbols)
        if not normalized:
            continue
        broker_symbol, market_symbol = normalized
        if market_symbol in binance_symbols and market_symbol not in symbols:
            symbols.append(market_symbol)
        context_by_symbol.setdefault(market_symbol, {"broker": broker, "broker_symbol": broker_symbol, "market_symbol": market_symbol})

    metadata = {
        "broker": broker,
        "broker_symbols": sorted(allowed_broker_symbols) if allowed_broker_symbols else "unrestricted",
        "coingecko_markets": len(markets),
        "binance_usdt_symbols": len(binance_symbols),
        "universe_symbols": len(symbols),
    }
    return symbols, context_by_symbol, metadata


def regime_alignment(direction: str, regime: str) -> str:
    if direction == "BUY" and regime in {"risk_on", "neutral"}:
        return "aligned"
    if direction == "SELL" and regime in {"risk_off", "extreme_greed", "neutral"}:
        return "aligned"
    if regime in {"extreme_fear"} and direction == "BUY":
        return "contrarian"
    return "mixed"


def run_session(
    *,
    config_dir: Path,
    top_assets: int,
    max_symbols: int,
    interval: str,
    lookback: int,
    capital_usd: float,
    max_risk_usd: float,
    valid_hours: int,
    min_quote_volume_usd: float,
    max_spread_percent: float,
    min_rr: float,
    extra_symbols: list[str],
    broker: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    symbols, context_by_symbol, metadata = build_universe(config_dir, top_assets, extra_symbols, broker)
    fear_greed = fetch_fear_greed()
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for symbol in symbols[:max_symbols]:
        context = dict(context_by_symbol.get(symbol, {}))
        context["regime"] = fear_greed["regime"]
        context["fear_greed"] = fear_greed
        try:
            candidate = build_candidate(
                symbol,
                interval,
                lookback,
                context=context,
                min_quote_volume_usd=min_quote_volume_usd,
                max_spread_percent=max_spread_percent,
                min_rr=min_rr,
            )
        except Exception as exc:
            errors.append({"source": "binance_market", "provider": "binance_public_api", "asset": symbol, "missing": ["market_data"], "error": str(exc)})
            continue
        if candidate:
            candidate["source_context"]["regime_alignment"] = regime_alignment(candidate["direction"], fear_greed["regime"])
            candidate["source_context"]["market_symbol"] = symbol
            candidate["source_context"]["broker"] = broker
            candidate["source_context"]["broker_symbol"] = context.get("broker_symbol", symbol)
            candidate["asset"] = context.get("broker_symbol", symbol)
            effective_valid_hours = min(valid_hours, 2) if interval == "15m" else valid_hours
            candidate = enrich_candidate(candidate, capital_usd, max_risk_usd, effective_valid_hours)
            if broker == "fbs":
                candidate["evidence"] = f"{candidate['evidence']}; broker=FBS; marketProxy={symbol}"
                candidate["risk_usd"] = None
                candidate["size"] = "TBD"
                candidate["source_context"]["sizing_note"] = "Volume Est. is proxy asset units. Confirm final FBS lot size and CFD contract value in the trading platform before execution."
            candidates.append(candidate)

    metadata.update({
        "scanned_symbols": min(len(symbols), max_symbols),
        "candidate_count": len(candidates),
        "error_count": len(errors),
        "fear_greed": fear_greed,
        "sources": ["binance_public_api", "coingecko_markets", "alternative_me_fng"],
    })
    return candidates + errors, metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a public-web crypto spot trading session report.")
    parser.add_argument("--config-dir", type=Path, default=Path("config"))
    parser.add_argument("--top-assets", type=int, default=DEFAULT_TOP_ASSETS)
    parser.add_argument("--max-symbols", type=int, default=60)
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--broker", default="fbs", choices=["fbs", "none"])
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--lookback", type=int, default=96)
    parser.add_argument("--min-quote-volume-usd", type=float, default=10_000_000)
    parser.add_argument("--max-spread-percent", type=float, default=0.06)
    parser.add_argument("--min-rr", type=float, default=1.6)
    parser.add_argument("--output-dir", type=Path, default=Path("sessions") / date.today().isoformat())
    args = parser.parse_args()

    params = session_params(args.config_dir)
    candidates, metadata = run_session(
        config_dir=args.config_dir,
        top_assets=args.top_assets,
        max_symbols=args.max_symbols,
        interval=args.interval,
        lookback=args.lookback,
        capital_usd=float(params["capital_usd"]),
        max_risk_usd=float(params["max_risk_usd"]),
        valid_hours=int(params["signal_window_hours"]),
        min_quote_volume_usd=args.min_quote_volume_usd,
        max_spread_percent=args.max_spread_percent,
        min_rr=args.min_rr,
        extra_symbols=[symbol.upper() for symbol in args.symbols],
        broker=args.broker,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = args.output_dir / "crypto-web-candidates.json"
    metadata_path = args.output_dir / "crypto-web-metadata.json"
    report_path = args.output_dir / "session-report.md"
    candidates_path.write_text(json.dumps(candidates, indent=2, sort_keys=True) + "\n")
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    report_path.write_text(render_report(candidates, float(params["max_risk_usd"]), metadata))
    print(json.dumps({"candidates": str(candidates_path), "metadata": str(metadata_path), "report": str(report_path), "count": len(candidates)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
