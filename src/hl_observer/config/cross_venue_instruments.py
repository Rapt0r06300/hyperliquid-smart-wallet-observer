"""Canonical Hyperliquid ↔ Binance perpetual instrument mapping.

Cross-venue economic evidence must never infer a Binance contract from a price
coincidence. The mapping is explicit and fail-closed; unsupported instruments
return ``None``.
"""
from __future__ import annotations

from collections.abc import Mapping

BINANCE_PERP_EXCEPTIONS: dict[str, str | None] = {
    "PEPE": "1000PEPEUSDT",
    "SHIB": "1000SHIBUSDT",
    "BONK": "1000BONKUSDT",
    "FLOKI": "1000FLOKIUSDT",
    "LUNC": "1000LUNCUSDT",
    "SATS": "1000SATSUSDT",
    "RATS": "1000RATSUSDT",
    "XEC": "1000XECUSDT",
    "WHYPE": None,
    "HYPE": None,
}

MAPPING_SCHEMA_VERSION = "cross_venue_instrument_mapping_v1"


def normalize_hl_coin(value: object) -> str | None:
    coin = str(value or "").strip().upper()
    if not coin or not coin.isalnum():
        return None
    return coin


def binance_perp_symbol(coin_hl: object) -> str | None:
    coin = normalize_hl_coin(coin_hl)
    if coin is None:
        return None
    if coin in BINANCE_PERP_EXCEPTIONS:
        return BINANCE_PERP_EXCEPTIONS[coin]
    if coin.startswith("K") and len(coin) > 1 and coin[1:].isalpha():
        return "1000" + coin[1:] + "USDT"
    return coin + "USDT"


def mapping_record(coin_hl: object, binance_symbol: object | None = None) -> dict[str, object]:
    coin = normalize_hl_coin(coin_hl)
    expected = binance_perp_symbol(coin)
    observed = str(binance_symbol or "").strip().upper() or None
    exact = bool(coin and expected and observed == expected)
    return {
        "schema_version": MAPPING_SCHEMA_VERSION,
        "hl_coin": coin,
        "binance_symbol_expected": expected,
        "binance_symbol_observed": observed,
        "exact": exact,
        "supported": expected is not None,
    }


def mapping_is_exact(row: Mapping[str, object]) -> bool:
    return mapping_record(row.get("coin"), row.get("binance_symbol"))["exact"] is True


__all__ = [
    "BINANCE_PERP_EXCEPTIONS",
    "MAPPING_SCHEMA_VERSION",
    "binance_perp_symbol",
    "mapping_is_exact",
    "mapping_record",
    "normalize_hl_coin",
]
