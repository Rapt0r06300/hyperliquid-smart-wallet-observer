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

#: Marchés Hyperliquid cotés par milliers d'unités (« kPEPE ») : leur contrat Binance est le « 1000… ».
#: Liste EXPLICITE, lue dans l'univers Hyperliquid le 2026-11-11. L'ancienne règle « commence par K »
#: prenait KAS et KAITO pour des « k-tokens » et fabriquait un contrat Binance qui n'existe pas
#: (« 1000ASUSDT »), refusé à chaque passe du collecteur de carnets. Un marché absent d'ici n'est
#: jamais multiplié : au pire il n'est pas apparié (refus), jamais apparié de travers.
HL_KILO_COINS: frozenset[str] = frozenset({"KBONK", "KFLOKI", "KLUNC", "KNEIRO", "KPEPE", "KSHIB"})

MAPPING_SCHEMA_VERSION = "cross_venue_instrument_mapping_v2"
ATOMIC_BBO_SOURCE_MODE = "CERTIFIED_ATOMIC_FOUR_SIDE_BBO_V1"


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
    if coin in HL_KILO_COINS:
        return "1000" + coin[1:] + "USDT"
    return coin + "USDT"


def hl_native_symbol(coin_hl: object) -> str | None:
    """Nom à envoyer à Hyperliquid, sensible à la casse : « kPEPE », jamais « KPEPE » (requête refusée)."""
    coin = normalize_hl_coin(coin_hl)
    if coin is None:
        return None
    return "k" + coin[1:] if coin in HL_KILO_COINS else coin


def mapping_record(coin_hl: object, binance_symbol: object | None = None) -> dict[str, object]:
    coin = normalize_hl_coin(coin_hl)
    expected = binance_perp_symbol(coin)
    observed = str(binance_symbol or "").strip().upper() or None
    contract_multiplier = 1000 if expected and expected.startswith("1000") else 1
    quote_currency = "USDT" if expected and expected.endswith("USDT") else None
    settlement_currency = quote_currency
    unit_equivalent = bool(expected and contract_multiplier == 1)
    exact = bool(coin and expected and observed == expected and unit_equivalent)
    return {
        "schema_version": MAPPING_SCHEMA_VERSION,
        "hl_coin": coin,
        "binance_symbol_expected": expected,
        "binance_symbol_observed": observed,
        "contract_multiplier": contract_multiplier if expected else None,
        "quote_currency": quote_currency,
        "settlement_currency": settlement_currency,
        "unit_equivalent": unit_equivalent,
        "exact": exact,
        "supported": expected is not None,
    }


def mapping_is_exact(row: Mapping[str, object]) -> bool:
    return mapping_record(row.get("coin"), row.get("binance_symbol"))["exact"] is True


__all__ = [
    "ATOMIC_BBO_SOURCE_MODE",
    "BINANCE_PERP_EXCEPTIONS",
    "HL_KILO_COINS",
    "MAPPING_SCHEMA_VERSION",
    "binance_perp_symbol",
    "hl_native_symbol",
    "mapping_is_exact",
    "mapping_record",
    "normalize_hl_coin",
]
