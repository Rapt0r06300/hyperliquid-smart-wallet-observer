"""Read-only aggregation of native Bybit/OKX instrument candidates."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from pydantic import BaseModel, Field

from hl_observer.markets.venues.bybit import BybitPublicClient
from hl_observer.markets.venues.models import VenueInstrument
from hl_observer.markets.venues.okx import OkxPublicClient
from hl_observer.markets.venues.symbols import base_from_canonical

SUPPORTED_NATIVE_VENUES: frozenset[str] = frozenset({"bybit", "okx"})


class _InstrumentClient(Protocol):
    async def discover_instruments(self, *, include_prelaunch: bool = False) -> list[VenueInstrument]: ...


class NativeVenueDiscoveryResult(BaseModel):
    instruments: list[VenueInstrument] = Field(default_factory=list)
    symbols_by_venue: dict[str, list[str]] = Field(default_factory=dict)
    canonical_venues: dict[str, list[str]] = Field(default_factory=dict)
    cross_venue_candidates: list[str] = Field(default_factory=list)
    hyperliquid_overlap: list[str] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)

    @property
    def candidates_count(self) -> int:
        return len(self.canonical_venues)


async def _discover_owned(venue: str, include_prelaunch: bool) -> list[VenueInstrument]:
    if venue == "bybit":
        async with BybitPublicClient() as client:
            return await client.discover_instruments(include_prelaunch=include_prelaunch)
    if venue == "okx":
        async with OkxPublicClient() as client:
            return await client.discover_instruments(include_prelaunch=include_prelaunch)
    raise ValueError(f"unsupported native venue: {venue}")


async def discover_native_venue_candidates(
    venues: list[str] | tuple[str, ...] = ("bybit", "okx"),
    *,
    include_prelaunch: bool = False,
    hyperliquid_coins: list[str] | None = None,
    clients: dict[str, _InstrumentClient] | None = None,
) -> NativeVenueDiscoveryResult:
    """Discover public perp candidates without failing the whole scan on one venue.

    `clients` is dependency injection for deterministic tests. Production callers normally
    leave it unset, in which case only public unauthenticated clients are constructed.
    """
    requested = list(dict.fromkeys(str(v).strip().lower() for v in venues if str(v).strip()))
    unsupported = sorted(set(requested) - SUPPORTED_NATIVE_VENUES)
    if unsupported:
        raise ValueError(f"unsupported native venue(s): {', '.join(unsupported)}")

    async def run_one(venue: str) -> tuple[str, list[VenueInstrument], str | None]:
        try:
            if clients and venue in clients:
                rows = await clients[venue].discover_instruments(include_prelaunch=include_prelaunch)
            else:
                rows = await _discover_owned(venue, include_prelaunch)
            return venue, rows, None
        except Exception as exc:  # noqa: BLE001 - one failed venue must not erase other data.
            return venue, [], str(exc)[:240]

    batches = await asyncio.gather(*(run_one(venue) for venue in requested))
    instruments: list[VenueInstrument] = []
    errors: dict[str, str] = {}
    symbols_by_venue: dict[str, list[str]] = {}
    canonical_map: dict[str, set[str]] = {}
    for venue, rows, error in batches:
        if error:
            errors[venue] = error
        symbols_by_venue[venue] = sorted(item.symbol for item in rows)
        instruments.extend(rows)
        for item in rows:
            canonical_map.setdefault(item.canonical_symbol, set()).add(venue)

    canonical_venues = {
        symbol: sorted(found_venues)
        for symbol, found_venues in sorted(canonical_map.items())
    }
    cross_venue = sorted(
        symbol for symbol, found_venues in canonical_venues.items() if len(found_venues) >= 2
    )
    hl_coins = {str(coin).strip().upper() for coin in (hyperliquid_coins or []) if str(coin).strip()}
    overlap = sorted(
        symbol for symbol in canonical_venues if base_from_canonical(symbol) in hl_coins
    )
    return NativeVenueDiscoveryResult(
        instruments=sorted(instruments, key=lambda item: (item.canonical_symbol, item.venue, item.symbol)),
        symbols_by_venue=symbols_by_venue,
        canonical_venues=canonical_venues,
        cross_venue_candidates=cross_venue,
        hyperliquid_overlap=overlap,
        errors=errors,
    )


__all__ = [
    "NativeVenueDiscoveryResult",
    "SUPPORTED_NATIVE_VENUES",
    "discover_native_venue_candidates",
]
