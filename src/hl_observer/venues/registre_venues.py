"""[AUD-268..291 / DATA-048,276,320] Aggregate venue capability registry.

Each venue exposes an offline normalizer boundary and an explicit live boundary.
Live pulls remain network-gated; this registry never enables execution.
"""
from __future__ import annotations

from . import (
    binance,
    bitget,
    bybit,
    coinbase,
    defillama,
    deribit,
    drift,
    dune,
    gate,
    glassnode,
    gmx,
    htx,
    hyperliquid,
    kraken,
    nansen,
    okx,
)

_MODULES = (
    hyperliquid,
    binance,
    bybit,
    okx,
    gate,
    bitget,
    coinbase,
    deribit,
    kraken,
    htx,
    drift,
    gmx,
    nansen,
    dune,
    glassnode,
    defillama,
)


def registre() -> dict:
    """venue -> capabilities (offline adapter plus live pull boundary)."""
    return {module.VENUE: module.capacites() for module in _MODULES}


def offline_ready() -> list:
    return sorted(
        venue for venue, capabilities in registre().items()
        if capabilities["adaptateur"] == "OFFLINE_READY"
    )


def par_frontiere_live() -> dict:
    """Group venues by live pull boundary."""
    out: dict[str, list[str]] = {}
    for venue, capabilities in registre().items():
        out.setdefault(capabilities["pull_live"], []).append(venue)
    return {key: sorted(values) for key, values in out.items()}


def ready_multi_venue(
    requis=("hyperliquid", "binance", "bybit", "okx", "gate", "bitget"),
) -> dict:
    """Require the six canonical venues to have offline-ready adapters."""
    reg = registre()
    manquants = [
        venue for venue in requis
        if reg.get(venue, {}).get("adaptateur") != "OFFLINE_READY"
    ]
    return {
        "ready": not manquants,
        "manquants": manquants,
        "offline_ready": offline_ready(),
        "n_venues": len(reg),
    }
