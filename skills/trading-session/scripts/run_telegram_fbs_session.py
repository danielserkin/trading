#!/usr/bin/env python3
"""Run a Telegram-signal driven FBS recommendation session.

This runner treats Telegram channels as the primary signal source. Market data is
used only to validate freshness, tradability, entry distance, and risk/reward.
It never places orders.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fetch_binance_market import get_json as binance_get_json
from normalize_candidates import normalize
from run_crypto_web_session import FBS_CRYPTO_SYMBOL_MAP, fetch_fear_greed, load_simple_yaml
from score_candidates import render_report, risk_reward


FOREX_CURRENCIES = {"AUD", "CAD", "CHF", "CNH", "EUR", "GBP", "HKD", "JPY", "MXN", "NOK", "NZD", "SEK", "SGD", "TRY", "USD", "ZAR"}
FOREX_CONTRACT_SIZE = 100000
METAL_CONTRACT_SIZES = {
    "XAUUSD": 100,
    "XAGUSD": 5000,
}
MIN_LOT = 0.01
LOT_STEP = 0.01

DEFAULT_FBS_SYMBOLS = {
    "crypto_cfd": sorted(FBS_CRYPTO_SYMBOL_MAP),
    "forex": [
        "AUDUSD",
        "AUDCAD",
        "AUDCHF",
        "AUDJPY",
        "AUDNZD",
        "CADCHF",
        "CADJPY",
        "CHFJPY",
        "EURAUD",
        "EURCAD",
        "EURCHF",
        "EURGBP",
        "EURJPY",
        "EURNZD",
        "EURUSD",
        "GBPAUD",
        "GBPCAD",
        "GBPCHF",
        "GBPJPY",
        "GBPNZD",
        "GBPUSD",
        "NZDUSD",
        "NZDCAD",
        "NZDCHF",
        "NZDJPY",
        "USDCAD",
        "USDCHF",
        "USDCNH",
        "USDHKD",
        "USDJPY",
        "USDMXN",
        "USDNOK",
        "USDSEK",
        "USDSGD",
        "USDTRY",
        "USDZAR",
    ],
    "metals": ["XAUUSD", "XAGUSD"],
    "energies": ["UKOIL", "USOIL", "XNGUSD"],
    "indices": ["AUS200", "DE30", "ES35", "EU50", "FRA40", "HK50", "JP225", "UK100", "US30", "US100", "US500"],
    "stocks": [
        "AAL",
        "AAPL",
        "ABNB",
        "AMD",
        "AMZN",
        "BA",
        "BABA",
        "BAC",
        "BIDU",
        "BP",
        "COIN",
        "COST",
        "CVX",
        "DAL",
        "DIS",
        "F",
        "GM",
        "GOOG",
        "GOOGL",
        "GS",
        "HD",
        "INTC",
        "JNJ",
        "JPM",
        "KO",
        "MA",
        "MCD",
        "META",
        "MRK",
        "MRNA",
        "MS",
        "MSFT",
        "NFLX",
        "NIO",
        "NKE",
        "NVDA",
        "PEP",
        "PFE",
        "PLTR",
        "PYPL",
        "SBUX",
        "TSLA",
        "UAL",
        "UBER",
        "ULVR",
        "V",
        "WMT",
        "XOM",
    ],
}

SYMBOL_ALIASES = {
    "GOLD": "XAUUSD",
    "SILVER": "XAGUSD",
    "OIL": "USOIL",
    "WTI": "USOIL",
    "BRENT": "UKOIL",
    "DAX": "DE30",
    "DAX30": "DE30",
    "DOW": "US30",
    "DJ30": "US30",
    "GER30": "DE30",
    "GER40": "DE30",
    "FTSE": "UK100",
    "FTSE100": "UK100",
    "CAC": "FRA40",
    "CAC40": "FRA40",
    "SP": "US500",
    "NASDAQ": "US100",
    "NAS100": "US100",
    "SPX": "US500",
    "SP500": "US500",
    "S&P500": "US500",
    "APPLE": "AAPL",
    "TESLA": "TSLA",
    "MICROSOFT": "MSFT",
    "NVIDIA": "NVDA",
    "META": "META",
    "FACEBOOK": "META",
    "GOOGLE": "GOOGL",
    "AMAZON": "AMZN",
    "NETFLIX": "NFLX",
    "DOGEUSD": "DOGUSD",
}
QUOTE_TO_USD_PROXY = {
    "AUD": ("AUDUSD", False),
    "CAD": ("USDCAD", True),
    "CHF": ("USDCHF", True),
    "CNH": ("USDCNH", True),
    "EUR": ("EURUSD", False),
    "GBP": ("GBPUSD", False),
    "HKD": ("USDHKD", True),
    "JPY": ("USDJPY", True),
    "MXN": ("USDMXN", True),
    "NOK": ("USDNOK", True),
    "NZD": ("NZDUSD", False),
    "SEK": ("USDSEK", True),
    "SGD": ("USDSGD", True),
    "TRY": ("USDTRY", True),
    "ZAR": ("USDZAR", True),
}
YAHOO_PROXY_SYMBOLS = {
    "AUDUSD": "AUDUSD=X",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "NZDUSD": "NZDUSD=X",
    "USDCAD": "USDCAD=X",
    "USDCHF": "USDCHF=X",
    "USDJPY": "USDJPY=X",
    "EURJPY": "EURJPY=X",
    "GBPJPY": "GBPJPY=X",
    "EURGBP": "EURGBP=X",
    "AUDCAD": "AUDCAD=X",
    "AUDCHF": "AUDCHF=X",
    "AUDJPY": "AUDJPY=X",
    "AUDNZD": "AUDNZD=X",
    "CADCHF": "CADCHF=X",
    "CADJPY": "CADJPY=X",
    "CHFJPY": "CHFJPY=X",
    "EURAUD": "EURAUD=X",
    "EURCAD": "EURCAD=X",
    "EURCHF": "EURCHF=X",
    "EURNZD": "EURNZD=X",
    "GBPAUD": "GBPAUD=X",
    "GBPCAD": "GBPCAD=X",
    "GBPCHF": "GBPCHF=X",
    "GBPNZD": "GBPNZD=X",
    "NZDCAD": "NZDCAD=X",
    "NZDCHF": "NZDCHF=X",
    "NZDJPY": "NZDJPY=X",
    "USDCNH": "USDCNH=X",
    "USDHKD": "USDHKD=X",
    "USDMXN": "USDMXN=X",
    "USDNOK": "USDNOK=X",
    "USDSEK": "USDSEK=X",
    "USDSGD": "USDSGD=X",
    "USDTRY": "USDTRY=X",
    "USDZAR": "USDZAR=X",
    "XAUUSD": "GC=F",
    "XAGUSD": "SI=F",
    "USOIL": "CL=F",
    "UKOIL": "BZ=F",
    "XNGUSD": "NG=F",
    "US30": "YM=F",
    "US100": "NQ=F",
    "US500": "ES=F",
    "AUS200": "SPI=F",
    "DE30": "FDAX.DE",
    "FRA40": "FCE.PA",
    "UK100": "Z.F",
    "JP225": "NKD=F",
    "AAPL": "AAPL",
    "AMZN": "AMZN",
    "COIN": "COIN",
    "GOOGL": "GOOGL",
    "META": "META",
    "MSFT": "MSFT",
    "NFLX": "NFLX",
    "NVDA": "NVDA",
    "TSLA": "TSLA",
}
COMMON_WORD_TOKENS = {
    "ACCOUNT",
    "ACTIVE",
    "ADMIN",
    "AFTER",
    "AGAIN",
    "ALERT",
    "ENTRY",
    "GOLD",
    "GROUP",
    "LIMIT",
    "MARKET",
    "MESSAGE",
    "PIPS",
    "PROFIT",
    "SIGNAL",
    "STOP",
    "TARGET",
    "TRADE",
}
AMBIGUOUS_SHORT_STOCK_TOKENS = {
    "AAL",
    "BA",
    "BP",
    "F",
    "GM",
    "GS",
    "KO",
    "MA",
    "MS",
    "V",
}

DIRECTION_RE = re.compile(r"\b(BUY|SELL|LONG|SHORT)\b", re.IGNORECASE)
COMPACT_DIRECTION_WORDS = {"BUY": "BUY", "LONG": "BUY", "SELL": "SELL", "SHORT": "SELL"}
PRICE_PATTERN = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
NUMBER_RE = re.compile(rf"(?<![A-Z0-9]){PRICE_PATTERN}(?![A-Z0-9])")
TP_PRICE_RE = re.compile(rf"\bTP(?:\d+|-\s*\d+|\s*#\s*\d+)?\b[^0-9]{{0,20}}(?:\d+\)\s*)?({PRICE_PATTERN})", re.IGNORECASE)
TAKE_PROFIT_PRICE_RE = re.compile(rf"\b(?:TAKE[-\s]*PROFIT|PROFIT\s*TARGETS?|TARGET\s*\d*|OBJETIVO)\b[^0-9]{{0,20}}(?:\d+\)\s*)?({PRICE_PATTERN})", re.IGNORECASE)
LABEL_PATTERNS = {
    "entry": re.compile(rf"\b(?:ENTRY(?:\s+(?:PRICE|POINT|ZONE|LEVEL|TARGETS?))?|ENTER|ENTRADA|OPEN|PRICE|BUY(?:\s+LIMIT)?|SELL(?:\s+LIMIT)?)\b[^0-9]{{0,40}}(?:\d+\)\s*)?({PRICE_PATTERN}(?:\s*[-/]\s*{PRICE_PATTERN})?)", re.IGNORECASE),
    "stop_loss": re.compile(rf"\b(?:SL|STOP[-\s]*LOSS|STOPLOSS|STOP|S/L|STOP\s*(?:TARGETS?|LOSS\s*TARGET)?)\b[^0-9]{{0,20}}(?:\d+\)\s*)?({PRICE_PATTERN})", re.IGNORECASE),
    "take_profit": TP_PRICE_RE,
}


@dataclass(frozen=True)
class ChannelConfig:
    id: str
    handle: str
    enabled: bool = True
    priority: int = 3
    max_age_hours: int | None = None
    markets: tuple[str, ...] = ()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_sources(config_dir: Path) -> dict[str, Any]:
    return load_simple_yaml(config_dir / "sources.yaml") or load_simple_yaml(config_dir / "sources.example.yaml")


def session_params(config_dir: Path) -> dict[str, Any]:
    example = load_simple_yaml(config_dir / "session-params.example.yaml")
    local = load_simple_yaml(config_dir / "session-params.yaml")
    merged: dict[str, Any] = {
        "capital_usd": 100.0,
        "max_risk_usd": 2.0,
        "signal_window_hours": 24,
        "max_final_candidates": 5,
        "primary_count": 3,
        "backup_count": 2,
    }
    merged.update(example or {})
    merged.update(local or {})
    return merged


def telegram_source_config(config_dir: Path) -> dict[str, Any]:
    for source in load_sources(config_dir).get("sources", []):
        if isinstance(source, dict) and source.get("type") == "telegram_signals":
            return source
    return {}


def fbs_universe(config_dir: Path) -> tuple[set[str], dict[str, str], dict[str, list[str]]]:
    symbols_by_market = {key: list(value) for key, value in DEFAULT_FBS_SYMBOLS.items()}
    for source in load_sources(config_dir).get("sources", []):
        if not isinstance(source, dict):
            continue
        if source.get("type") not in {"fbs_market_universe", "fbs_crypto_cfd"}:
            continue
        if isinstance(source.get("symbols_by_market"), dict):
            for market, symbols in source["symbols_by_market"].items():
                if isinstance(symbols, list):
                    symbols_by_market[str(market)] = [str(item).upper() for item in symbols]
        if isinstance(source.get("broker_symbols"), list):
            symbols_by_market.setdefault("crypto_cfd", [])
            symbols_by_market["crypto_cfd"] = [str(item).upper() for item in source["broker_symbols"]]

    allowed = {symbol.upper() for symbols in symbols_by_market.values() for symbol in symbols}
    aliases = dict(SYMBOL_ALIASES)
    for source in load_sources(config_dir).get("sources", []):
        if isinstance(source, dict) and isinstance(source.get("symbol_aliases"), dict):
            aliases.update({str(key).upper(): str(value).upper() for key, value in source["symbol_aliases"].items()})
    return allowed, aliases, symbols_by_market


def channel_configs(config_dir: Path, default_window_hours: int) -> list[ChannelConfig]:
    source = telegram_source_config(config_dir)
    channels = []
    for item in source.get("channels", []):
        if not isinstance(item, dict):
            continue
        handle = str(item.get("handle") or item.get("id") or "").strip()
        if not handle:
            continue
        channels.append(
            ChannelConfig(
                id=str(item.get("id") or handle).strip(),
                handle=handle,
                enabled=bool(item.get("enabled", True)),
                priority=int(item.get("priority", source.get("default_priority", 3))),
                max_age_hours=int(item.get("max_age_hours", source.get("max_age_hours", default_window_hours))),
                markets=tuple(str(market) for market in item.get("markets", [])),
            )
        )
    return channels


async def fetch_telegram_messages(config_dir: Path, limit_per_channel: int, default_window_hours: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        from telethon import TelegramClient  # type: ignore
    except Exception as exc:
        return [], [{"source": "telegram_signal", "provider": "telegram", "asset": "", "missing": ["telegram_client"], "error": f"telethon import failed: {exc}"}]

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    session_name = os.getenv("TELEGRAM_SESSION", str(config_dir.parent / "telegram-fbs.session"))
    if not api_id or not api_hash:
        return [], [{"source": "telegram_signal", "provider": "telegram", "asset": "", "missing": ["telegram_credentials"], "error": "TELEGRAM_API_ID and TELEGRAM_API_HASH are required"}]

    messages: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    async with TelegramClient(session_name, int(api_id), api_hash) as client:
        for channel in channel_configs(config_dir, default_window_hours):
            if not channel.enabled:
                continue
            try:
                async for message in client.iter_messages(channel.handle, limit=limit_per_channel):
                    if not message.message:
                        continue
                    message_date = message.date.astimezone(timezone.utc) if message.date.tzinfo else message.date.replace(tzinfo=timezone.utc)
                    max_age = timedelta(hours=channel.max_age_hours or default_window_hours)
                    if utc_now() - message_date > max_age:
                        continue
                    messages.append(
                        {
                            "channel": channel.id,
                            "handle": channel.handle,
                            "priority": channel.priority,
                            "text": message.message,
                            "timestamp": message_date.isoformat(),
                            "message_id": message.id,
                            "message_url": build_message_url(channel.handle, message.id),
                            "has_media": bool(message.media),
                        }
                    )
            except Exception as exc:
                errors.append({"source": "telegram_signal", "provider": channel.id, "asset": "", "missing": ["telegram_channel"], "error": str(exc)})
    return messages, errors


def build_message_url(handle: str, message_id: int) -> str:
    clean = handle.removeprefix("@").strip()
    if clean.startswith("https://t.me/"):
        clean = clean.removeprefix("https://t.me/").strip("/")
    if not clean or clean.startswith("-"):
        return str(message_id)
    return f"https://t.me/{clean}/{message_id}"


def parse_offline_inputs(input_paths: list[Path]) -> list[dict[str, Any]]:
    messages = []
    for path in input_paths:
        if not path.exists():
            continue
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text())
            items = data if isinstance(data, list) else [data]
            for index, item in enumerate(items):
                if isinstance(item, dict):
                    messages.append(
                        {
                            "channel": str(item.get("channel") or item.get("provider") or path.stem),
                            "handle": str(item.get("handle") or item.get("channel") or path.stem),
                            "priority": int(item.get("priority", 3)),
                            "text": str(item.get("text") or item.get("message") or item.get("raw_text") or ""),
                            "timestamp": str(item.get("timestamp") or utc_now().isoformat()),
                            "message_id": item.get("message_id", index + 1),
                            "message_url": str(item.get("message_url") or ""),
                            "has_media": bool(item.get("has_media", False)),
                        }
                    )
        else:
            messages.append(
                {
                    "channel": path.stem,
                    "handle": path.stem,
                    "priority": 3,
                    "text": path.read_text(),
                    "timestamp": utc_now().isoformat(),
                    "message_id": 1,
                    "message_url": str(path),
                    "has_media": False,
                }
            )
    return messages


def parse_signal(message: dict[str, Any], allowed_symbols: set[str], aliases: dict[str, str]) -> dict[str, Any]:
    text = str(message.get("text") or "")
    upper_text = text.upper()
    normalized_text = upper_text.replace("#", " ").replace("_", " ")
    direction_match = DIRECTION_RE.search(normalized_text)
    symbol, symbol_status = extract_symbol(upper_text, normalized_text, allowed_symbols, aliases)
    direction = extract_direction(normalized_text, direction_match, symbol, allowed_symbols, aliases)

    entry = parse_entry(normalized_text) or infer_entry(normalized_text, symbol, direction_match)
    stop_loss = parse_first_label(normalized_text, "stop_loss")
    take_profits = parse_take_profits(normalized_text)
    item = {
        "source": "telegram_signal",
        "provider": message.get("channel"),
        "channel": message.get("channel"),
        "asset": symbol,
        "direction": direction,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profits": take_profits,
        "timestamp": message.get("timestamp"),
        "evidence": compact_text(text),
        "confidence": "medium",
        "raw_text": text,
        "message_id": message.get("message_id"),
        "message_url": message.get("message_url"),
        "expert_signal": True,
        "parsed_by": "regex_v1",
        "channel_priority": message.get("priority", 3),
        "image_evidence": "media_attached" if message.get("has_media") else "",
    }
    candidate = normalize(item, "telegram_signal")
    candidate.update({key: value for key, value in item.items() if key not in candidate or key in {"message_id", "message_url", "raw_text", "channel_priority", "expert_signal", "parsed_by", "image_evidence"}})
    if symbol_status == "missing":
        candidate.setdefault("missing", []).append("broker_universe")
    elif symbol_status == "plausible_unconfirmed":
        candidate.setdefault("missing", []).append("unknown_fbs_symbol")
        candidate["symbol_status"] = "plausible_unconfirmed"
    return candidate


def extract_direction(
    text: str,
    direction_match: re.Match[str] | None,
    symbol: str | None,
    allowed_symbols: set[str],
    aliases: dict[str, str],
) -> str | None:
    if direction_match:
        return COMPACT_DIRECTION_WORDS[direction_match.group(1).upper()]

    compact = re.sub(r"[^A-Z0-9]", "", text.upper())
    symbol_tokens = set(allowed_symbols)
    symbol_tokens.update(aliases)
    if symbol:
        symbol_tokens.add(symbol)
    for token in sorted(symbol_tokens, key=len, reverse=True):
        if token in AMBIGUOUS_SHORT_STOCK_TOKENS:
            continue
        mapped = aliases.get(token, token)
        if mapped not in allowed_symbols:
            continue
        for raw_direction, normalized_direction in COMPACT_DIRECTION_WORDS.items():
            if f"{token}{raw_direction}" in compact or f"{raw_direction}{token}" in compact:
                return normalized_direction
    return None


def extract_symbol(raw_text: str, text: str, allowed_symbols: set[str], aliases: dict[str, str]) -> tuple[str | None, str]:
    for base, quote in re.findall(r"#?\b([A-Z]{2,8})\s*/\s*([A-Z]{2,8})\b", raw_text.upper()):
        mapped = aliases.get(f"{base}{quote}", f"{base}{quote}")
        if mapped in allowed_symbols:
            return mapped, "confirmed"
    for base in re.findall(r"#?\b([A-Z]{2,8})\s*/\s*USDT\b", raw_text.upper()):
        mapped = aliases.get(f"{base}USD", f"{base}USD")
        if mapped in allowed_symbols:
            return mapped, "confirmed"
    cashtag_tokens = [item.upper() for item in re.findall(r"#([A-Z]{1,8}\d{0,3})\b", raw_text)]
    tokens = [*cashtag_tokens, *re.findall(r"[A-Z]{2,12}\d{0,3}", text)]
    for token in tokens:
        alias = aliases.get(token, token)
        if token not in cashtag_tokens and alias in AMBIGUOUS_SHORT_STOCK_TOKENS:
            continue
        if alias in allowed_symbols:
            return alias, "confirmed"
    compact = text.replace(" ", "")
    for token, alias in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in allowed_symbols and token in compact:
            return alias, "confirmed"
    for symbol in sorted(allowed_symbols, key=len, reverse=True):
        if symbol in AMBIGUOUS_SHORT_STOCK_TOKENS:
            continue
        if symbol in compact:
            return symbol, "confirmed"
    for token in cashtag_tokens:
        if is_plausible_stock_symbol(token):
            return token, "plausible_unconfirmed"
    return None, "missing"


def is_plausible_stock_symbol(token: str) -> bool:
    return 1 <= len(token) <= 6 and token not in COMMON_WORD_TOKENS and not token.endswith("USD")


def parse_entry(text: str) -> float | None:
    match = LABEL_PATTERNS["entry"].search(text)
    if not match:
        return None
    raw = match.group(1)
    numbers = [parse_number(item) for item in NUMBER_RE.findall(raw)]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def infer_entry(text: str, symbol: str | None, direction_match: re.Match[str] | None) -> float | None:
    cutoff = len(text)
    for label in ("SL", "STOP", "TP", "TARGET", "OBJETIVO"):
        index = text.find(label)
        if index != -1:
            cutoff = min(cutoff, index)
    head = text[:cutoff]
    start = 0
    if symbol and symbol in head:
        start = head.find(symbol) + len(symbol)
    if direction_match:
        start = max(start, direction_match.end())
    numbers = [parse_number(item) for item in NUMBER_RE.findall(head[start:])]
    if not numbers:
        return None
    return sum(numbers[:2]) / min(len(numbers), 2)


def parse_first_label(text: str, label: str) -> float | None:
    match = LABEL_PATTERNS[label].search(text)
    if not match:
        return None
    return parse_number(match.group(1))


def parse_take_profits(text: str) -> list[float]:
    matches: list[tuple[int, float]] = []

    for match in TP_PRICE_RE.finditer(text):
        matches.append((match.start(1), parse_number(match.group(1))))

    for match in TAKE_PROFIT_PRICE_RE.finditer(text):
        value = parse_number(match.group(1))
        prefix = text[match.end() - len(match.group(1)) - 8 : match.end() - len(match.group(1))]
        if value <= 10 and re.search(r"\bTP\s*#?\s*$|\bTP\d+\W*$", prefix, re.IGNORECASE):
            continue
        matches.append((match.start(1), value))

    deduped: list[float] = []
    for _, value in sorted(matches, key=lambda item: item[0]):
        if value not in deduped:
            deduped.append(value)
    return deduped


def parse_number(value: str) -> float:
    return float(value.replace(",", ""))


def compact_text(text: str, limit: int = 180) -> str:
    clean = " ".join(text.split()).replace("|", "/")
    return clean if len(clean) <= limit else clean[: limit - 3] + "..."


def validate_candidate(candidate: dict[str, Any], params: dict[str, Any], symbols_by_market: dict[str, list[str]], fear_greed: dict[str, Any]) -> dict[str, Any]:
    candidate["broker"] = "fbs"
    candidate["broker_symbol"] = candidate.get("asset")
    candidate["signal_status"] = "vigente"
    candidate["market_valid"] = True
    candidate["source_context"] = {
        "broker": "fbs",
        "signal_origin": "telegram",
        "fear_greed": fear_greed,
        "market_type": market_type_for_asset(str(candidate.get("asset") or ""), symbols_by_market),
    }

    timestamp = parse_datetime(candidate.get("timestamp"))
    if timestamp:
        freshness = max(0, int((utc_now() - timestamp).total_seconds() / 60))
        candidate["freshness_minutes"] = freshness
        if freshness > int(params.get("signal_window_hours", 24)) * 60:
            candidate["signal_status"] = "vencida"
            candidate["market_valid"] = False
            candidate.setdefault("missing", []).append("freshness")

    if candidate.get("asset") in FBS_CRYPTO_SYMBOL_MAP:
        validate_crypto_proxy(candidate, params)
    elif str(candidate.get("asset") or "") in YAHOO_PROXY_SYMBOLS:
        validate_yahoo_proxy(candidate)
    else:
        candidate["current_price"] = "TBD"
        candidate["analysis"] = {"market_data_note": "No public validator configured for this FBS market. Confirm price/spread in FBS before execution."}
        candidate["market_valid"] = False
        candidate.setdefault("missing", []).append("market_data")

    rr = risk_reward(candidate)
    min_rr = float(params.get("min_rr", 1.6))
    structural_reason = validate_trade_structure(candidate)
    if structural_reason:
        candidate["signal_status"] = "descartada"
        candidate["market_valid"] = False
        candidate["discard_reason"] = structural_reason
    if rr is not None and rr < min_rr:
        candidate["signal_status"] = "descartada"
        candidate["market_valid"] = False
        candidate["discard_reason"] = f"rr_below_{min_rr}"

    if candidate.get("entry") is not None and candidate.get("current_price") not in (None, "TBD"):
        entry = float(candidate["entry"])
        current = float(candidate["current_price"])
        distance = abs(current - entry) / entry * 100 if entry else 0.0
        candidate["entry_distance_percent"] = round(distance, 4)
        max_distance = float(params.get("market_data", {}).get("max_entry_distance_percent") or 1.2)
        if distance > max_distance:
            candidate["signal_status"] = "llegada_tarde"
            candidate["execution_bias"] = "solo con pullback" if candidate.get("direction") == "BUY" else "solo con retroceso"
            candidate["modification_note"] = f"Current price is {distance:.2f}% from expert entry; wait for price to return near the original signal."
        else:
            candidate["execution_bias"] = "tomable ahora"

    market_state_reason = validate_current_market_state(candidate)
    if market_state_reason:
        candidate["signal_status"] = "descartada"
        candidate["market_valid"] = False
        candidate["discard_reason"] = market_state_reason

    apply_position_sizing(candidate, float(params.get("max_risk_usd", 2.0)))
    return candidate


def validate_crypto_proxy(candidate: dict[str, Any], params: dict[str, Any]) -> None:
    market_symbol = FBS_CRYPTO_SYMBOL_MAP[str(candidate["asset"])]
    try:
        ticker = binance_get_json("/api/v3/ticker/bookTicker", {"symbol": market_symbol})
        ticker_24h = binance_get_json("/api/v3/ticker/24hr", {"symbol": market_symbol})
    except Exception as exc:
        candidate["market_valid"] = False
        candidate.setdefault("missing", []).append("market_data")
        candidate["error"] = str(exc)
        return
    bid = float(ticker["bidPrice"])
    ask = float(ticker["askPrice"])
    current = ask if candidate.get("direction") == "BUY" else bid
    spread = ask - bid
    spread_percent = spread / current * 100 if current else 0.0
    candidate["market_symbol"] = market_symbol
    candidate["current_price"] = round(current, 8)
    candidate["analysis"] = {
        "bid": round(bid, 8),
        "ask": round(ask, 8),
        "spread": round(spread, 8),
        "spread_percent": round(spread_percent, 5),
        "quote_volume_24h": float(ticker_24h.get("quoteVolume", 0)),
        "market_proxy": "binance_public_api",
    }
    candidate["source_context"]["market_symbol"] = market_symbol
    candidate["source_context"]["market_proxy"] = "binance_public_api"
    max_spread = float(params.get("market_data", {}).get("max_spread_percent") or 0.06)
    if spread_percent > max_spread:
        candidate["market_valid"] = False
        candidate.setdefault("missing", []).append("spread")


def validate_yahoo_proxy(candidate: dict[str, Any]) -> None:
    asset = str(candidate.get("asset") or "")
    proxy_symbol = YAHOO_PROXY_SYMBOLS[asset]
    try:
        current = fetch_yahoo_current(asset)
    except Exception as exc:
        candidate["market_valid"] = False
        candidate.setdefault("missing", []).append("market_data")
        candidate["error"] = str(exc)
        return
    if current in (None, ""):
        candidate["market_valid"] = False
        candidate.setdefault("missing", []).append("market_data")
        return
    candidate["market_symbol"] = proxy_symbol
    candidate["current_price"] = round(float(current), 8)
    candidate["analysis"] = {
        "market_proxy": "yahoo_finance_chart",
        "proxy_symbol": proxy_symbol,
        "regular_market_price": round(float(current), 8),
        "market_data_note": "Public proxy only. Confirm executable bid/ask, spread, trading hours, and CFD contract specs in FBS before execution.",
    }
    candidate["source_context"]["market_symbol"] = proxy_symbol
    candidate["source_context"]["market_proxy"] = "yahoo_finance_chart"


def fetch_yahoo_current(asset: str) -> float | None:
    proxy_symbol = YAHOO_PROXY_SYMBOLS.get(asset)
    if not proxy_symbol:
        return None
    encoded = urllib.parse.quote(proxy_symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=1d&interval=1m"
    request = urllib.request.Request(url, headers={"User-Agent": "trading-session/1.0"})
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = (payload.get("chart", {}).get("result") or [])[0]
    meta = result.get("meta", {})
    current = meta.get("regularMarketPrice") or meta.get("chartPreviousClose")
    return float(current) if current not in (None, "") else None


def apply_position_sizing(candidate: dict[str, Any], max_risk_usd: float) -> None:
    sizing = estimate_fbs_lot_size(candidate, max_risk_usd)
    if not sizing:
        candidate["risk_usd"] = None
        candidate["size"] = "TBD"
        return

    candidate["risk_usd"] = sizing["risk_usd"]
    candidate["size"] = sizing["size"]
    candidate["position_sizing"] = sizing
    candidate["volume_estimate"] = {
        "units": sizing["lot_size"],
        "unit": "lot",
        "notional_usd": sizing.get("notional_usd"),
    }
    candidate["sizing_note"] = sizing["note"]


def estimate_fbs_lot_size(candidate: dict[str, Any], max_risk_usd: float) -> dict[str, Any] | None:
    asset = str(candidate.get("asset") or "")
    direction = candidate.get("direction")
    entry = candidate.get("entry")
    stop_loss = candidate.get("stop_loss")
    take_profits = candidate.get("take_profits") or []
    if direction not in {"BUY", "SELL"} or entry is None or stop_loss is None:
        return None

    contract_size = fbs_contract_size(asset)
    quote_currency = asset[3:6] if is_forex_symbol(asset) else "USD" if asset in METAL_CONTRACT_SIZES else None
    if contract_size is None or quote_currency is None:
        return None

    quote_to_usd = quote_currency_to_usd(quote_currency)
    if quote_to_usd is None:
        return None

    entry_f = float(entry)
    stop_f = float(stop_loss)
    risk_per_lot_usd = abs(entry_f - stop_f) * contract_size * quote_to_usd
    if risk_per_lot_usd <= 0:
        return None

    raw_lots = max_risk_usd / risk_per_lot_usd
    lot_size = round(max(MIN_LOT, int(raw_lots / LOT_STEP) * LOT_STEP), 2)
    risk_usd = round(risk_per_lot_usd * lot_size, 2)
    reward_usd = None
    if take_profits:
        reward_usd = round(abs(float(take_profits[0]) - entry_f) * contract_size * quote_to_usd * lot_size, 2)
    notional_usd = round(entry_f * contract_size * quote_to_usd * lot_size, 2)
    note = (
        f"lotaje indicativo FBS: {lot_size:.2f} lot, riesgo aprox {risk_usd:.2f} USD"
        + (f", TP1 aprox {reward_usd:.2f} USD" if reward_usd is not None else "")
        + "; confirmar valor de punto en FBS antes de abrir"
    )
    return {
        "lot_size": lot_size,
        "size": f"{lot_size:.2f} lot",
        "risk_usd": risk_usd,
        "max_risk_usd": round(max_risk_usd, 2),
        "risk_per_lot_usd": round(risk_per_lot_usd, 2),
        "tp1_profit_usd": reward_usd,
        "notional_usd": notional_usd,
        "contract_size": contract_size,
        "quote_currency": quote_currency,
        "quote_to_usd": round(quote_to_usd, 8),
        "note": note,
    }


def fbs_contract_size(asset: str) -> int | None:
    if is_forex_symbol(asset):
        return FOREX_CONTRACT_SIZE
    return METAL_CONTRACT_SIZES.get(asset)


def is_forex_symbol(asset: str) -> bool:
    return len(asset) == 6 and asset[:3] in FOREX_CURRENCIES and asset[3:] in FOREX_CURRENCIES


def quote_currency_to_usd(currency: str) -> float | None:
    if currency == "USD":
        return 1.0
    proxy = QUOTE_TO_USD_PROXY.get(currency)
    if not proxy:
        return None
    asset, inverse = proxy
    price = fetch_yahoo_current(asset)
    if price in (None, 0):
        return None
    return 1 / price if inverse else price


def validate_trade_structure(candidate: dict[str, Any]) -> str | None:
    direction = candidate.get("direction")
    entry = candidate.get("entry")
    stop_loss = candidate.get("stop_loss")
    take_profits = candidate.get("take_profits") or []
    if direction not in {"BUY", "SELL"} or entry is None or stop_loss is None or not take_profits:
        return None
    entry_f = float(entry)
    stop_f = float(stop_loss)
    first_tp = float(take_profits[0])
    if direction == "BUY" and not (stop_f < entry_f < first_tp):
        return "invalid_buy_structure"
    if direction == "SELL" and not (first_tp < entry_f < stop_f):
        return "invalid_sell_structure"
    return None


def validate_current_market_state(candidate: dict[str, Any]) -> str | None:
    direction = candidate.get("direction")
    current = candidate.get("current_price")
    stop_loss = candidate.get("stop_loss")
    take_profits = candidate.get("take_profits") or []
    if direction not in {"BUY", "SELL"} or current in (None, "TBD") or stop_loss is None or not take_profits:
        return None
    current_f = float(current)
    stop_f = float(stop_loss)
    first_tp = float(take_profits[0])
    if direction == "BUY":
        if current_f <= stop_f:
            return "sl_already_hit"
        if current_f >= first_tp:
            return "tp_already_hit"
    if direction == "SELL":
        if current_f >= stop_f:
            return "sl_already_hit"
        if current_f <= first_tp:
            return "tp_already_hit"
    return None


def market_type_for_asset(asset: str, symbols_by_market: dict[str, list[str]]) -> str:
    for market, symbols in symbols_by_market.items():
        if asset in symbols:
            return market
    return "unknown"


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def dedupe(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    unique = []
    for candidate in candidates:
        key = (
            candidate.get("asset"),
            candidate.get("direction"),
            round(float(candidate.get("entry") or 0), 6),
            round(float(candidate.get("stop_loss") or 0), 6),
            tuple(round(float(tp), 6) for tp in candidate.get("take_profits") or []),
        )
        if key in seen:
            candidate["signal_status"] = "duplicada"
            candidate["market_valid"] = False
            candidate.setdefault("missing", []).append("duplicate")
        else:
            seen.add(key)
            unique.append(candidate)
    return unique


def run_session(config_dir: Path, limit_per_channel: int, input_paths: list[Path]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = session_params(config_dir)
    allowed_symbols, aliases, symbols_by_market = fbs_universe(config_dir)
    fear_greed = fetch_fear_greed()
    messages = parse_offline_inputs(input_paths)
    errors: list[dict[str, Any]] = []
    if not messages:
        fetched, errors = asyncio.run(fetch_telegram_messages(config_dir, limit_per_channel, int(params.get("signal_window_hours", 24))))
        messages.extend(fetched)

    candidates = [parse_signal(message, allowed_symbols, aliases) for message in messages]
    candidates = [validate_candidate(candidate, params, symbols_by_market, fear_greed) for candidate in candidates]
    candidates = dedupe(candidates)
    metadata = {
        "broker": "fbs",
        "broker_symbols": sorted(allowed_symbols),
        "sources": ["telegram_channels", "fbs_allowlist", "market_validators"],
        "telegram_messages_reviewed": len(messages),
        "telegram_channels": [channel.id for channel in channel_configs(config_dir, int(params.get("signal_window_hours", 24))) if channel.enabled],
        "candidate_count": len(candidates),
        "error_count": len(errors),
        "fear_greed": fear_greed,
        "mode": "recommend_only",
        "market_scope": sorted(symbols_by_market),
    }
    return candidates + errors, metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an FBS recommendation report from Telegram expert signals.")
    parser.add_argument("--config-dir", type=Path, default=Path("config"))
    parser.add_argument("--limit-per-channel", type=int, default=80)
    parser.add_argument("--input", nargs="*", type=Path, default=[], help="Optional offline Telegram export JSON/TXT files for dry runs.")
    parser.add_argument("--output-dir", type=Path, default=Path("sessions") / date.today().isoformat())
    args = parser.parse_args()

    params = session_params(args.config_dir)
    candidates, metadata = run_session(args.config_dir, args.limit_per_channel, args.input)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = args.output_dir / "telegram-fbs-candidates.json"
    metadata_path = args.output_dir / "telegram-fbs-metadata.json"
    report_path = args.output_dir / "session-report.md"
    candidates_path.write_text(json.dumps(candidates, indent=2, sort_keys=True) + "\n")
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    report_path.write_text(render_report(candidates, float(params["max_risk_usd"]), metadata))
    print(json.dumps({"candidates": str(candidates_path), "metadata": str(metadata_path), "report": str(report_path), "count": len(candidates)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
