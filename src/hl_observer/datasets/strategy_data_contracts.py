"""Replay-grade data contracts for Alina SmartFlow strategies.

These contracts describe the evidence a validation window must contain. They are
intentionally stricter than diagnostic requirements: missing families keep a window
PARTIAL instead of being silently substituted.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

CORE_VENUES = ("hyperliquid", "binance", "bybit", "okx")


CROSS_VENUE_REQUIRED_FAMILIES: dict[str, frozenset[str]] = {
    "hyperliquid": frozenset(
        {
            "bbo",
            "l2Book",
            "trades",
            "activeAssetCtx",
            "instrument_metadata",
        }
    ),
    "binance": frozenset(
        {
            "bbo",
            "l2Book",
            "agg_trades",
            "mark_funding",
            "open_interest",
            "instrument_metadata",
        }
    ),
    "bybit": frozenset(
        {
            "l2Book",
            "trades",
            "ticker",
            "instrument_metadata",
        }
    ),
    "okx": frozenset(
        {
            "l2Book",
            "trades",
            "ticker",
            "funding",
            "open_interest",
            "mark_price",
            "index_price",
            "instrument_metadata",
        }
    ),
}


LEAD_LAG_REQUIRED_FAMILIES: dict[str, frozenset[str]] = {
    "hyperliquid": frozenset({"bbo", "l2Book", "trades", "instrument_metadata"}),
    "binance": frozenset({"bbo", "l2Book", "agg_trades", "instrument_metadata"}),
    "bybit": frozenset({"l2Book", "trades", "ticker", "instrument_metadata"}),
    "okx": frozenset({"l2Book", "trades", "ticker", "instrument_metadata"}),
}


COPY_VAULT_REQUIRED_FAMILIES: dict[str, frozenset[str]] = {
    "hyperliquid": frozenset(
        {
            "userFills",
            "bbo",
            "l2Book",
            "trades",
            "activeAssetCtx",
            "instrument_metadata",
        }
    )
}


@dataclass(frozen=True, slots=True)
class StrategyDataContract:
    strategy: str
    required_families_by_venue: Mapping[str, frozenset[str]]
    max_receive_skew_ms: float | None
    max_exchange_skew_ms: float | None
    min_sync_samples: int
    require_exact_instrument_mapping: bool
    require_same_collection_run: bool
    require_reconciliation: bool

    def for_venues(self, venues: Iterable[str]) -> dict[str, frozenset[str]]:
        selected: dict[str, frozenset[str]] = {}
        for venue in venues:
            key = str(venue).strip().lower()
            if key in self.required_families_by_venue:
                selected[key] = self.required_families_by_venue[key]
        return selected


CONTRACTS: dict[str, StrategyDataContract] = {
    "cross_venue": StrategyDataContract(
        strategy="cross_venue",
        required_families_by_venue=CROSS_VENUE_REQUIRED_FAMILIES,
        max_receive_skew_ms=250.0,
        max_exchange_skew_ms=250.0,
        min_sync_samples=20,
        require_exact_instrument_mapping=True,
        require_same_collection_run=True,
        require_reconciliation=True,
    ),
    "lead_lag": StrategyDataContract(
        strategy="lead_lag",
        required_families_by_venue=LEAD_LAG_REQUIRED_FAMILIES,
        max_receive_skew_ms=100.0,
        max_exchange_skew_ms=100.0,
        min_sync_samples=50,
        require_exact_instrument_mapping=True,
        require_same_collection_run=True,
        require_reconciliation=True,
    ),
    "copy_vault": StrategyDataContract(
        strategy="copy_vault",
        required_families_by_venue=COPY_VAULT_REQUIRED_FAMILIES,
        max_receive_skew_ms=250.0,
        max_exchange_skew_ms=250.0,
        min_sync_samples=20,
        require_exact_instrument_mapping=False,
        require_same_collection_run=True,
        require_reconciliation=True,
    ),
}


def get_strategy_data_contract(strategy: str) -> StrategyDataContract:
    key = str(strategy or "").strip().lower().replace("-", "_")
    try:
        return CONTRACTS[key]
    except KeyError as exc:
        raise ValueError(f"unknown strategy data contract: {strategy}") from exc


def missing_required_families(
    manifests: Iterable[Mapping[str, Any]],
    *,
    strategy: str,
    venues: Iterable[str],
) -> dict[str, list[str]]:
    contract = get_strategy_data_contract(strategy)
    required = contract.for_venues(venues)
    observed: dict[str, set[str]] = {venue: set() for venue in required}
    for manifest in manifests:
        venue = str(manifest.get("venue") or "").strip().lower()
        family = str(manifest.get("family") or "").strip()
        if venue in observed and family:
            observed[venue].add(family)
    return {
        venue: sorted(families - observed.get(venue, set()))
        for venue, families in required.items()
        if not families.issubset(observed.get(venue, set()))
    }


__all__ = [
    "CONTRACTS",
    "COPY_VAULT_REQUIRED_FAMILIES",
    "CORE_VENUES",
    "CROSS_VENUE_REQUIRED_FAMILIES",
    "LEAD_LAG_REQUIRED_FAMILIES",
    "StrategyDataContract",
    "get_strategy_data_contract",
    "missing_required_families",
]
