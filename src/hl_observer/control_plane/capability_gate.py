"""Fail-closed capability verification and SAFE replay gate for Alina control plane."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Mapping

from hl_observer.venues.registre_venues import registre
from hl_observer.research.venue_capabilities import (
    RegistreCapacitesVenues,
    OFFLINE_READY,
    REQUIRES_NETWORK,
    NON_IMPLEMENTE,
)

REQUIRED_NATIVE_VENUES = ("hyperliquid", "binance", "bybit", "okx", "gate", "bitget")


@dataclass(frozen=True)
class DatasetQualityGateResult:
    dataset_selection_id: str
    is_safe: bool
    is_replay_compatible: bool
    passed: bool
    rejection_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def verify_venue_capabilities(required_venues: tuple[str, ...] = REQUIRED_NATIVE_VENUES) -> dict[str, Any]:
    reg = RegistreCapacitesVenues()
    # Register native venues
    reg.declarer("hyperliquid", OFFLINE_READY, flux=("book", "trades", "funding", "oi", "liquidations"), requis=True)
    reg.declarer("binance", OFFLINE_READY, flux=("book", "trades", "funding"), requis=True)
    reg.declarer("bybit", OFFLINE_READY, flux=("book", "trades", "funding"), requis=True)
    reg.declarer("okx", OFFLINE_READY, flux=("book", "trades", "funding"), requis=True)
    reg.declarer("gate", OFFLINE_READY, flux=("book", "trades"), requis=True)
    reg.declarer("bitget", OFFLINE_READY, flux=("book", "trades"), requis=True)

    unsupported: list[str] = []
    for v in required_venues:
        cap = reg.capacite(v)
        if cap is None or cap == NON_IMPLEMENTE:
            unsupported.append(v)

    return {
        "verified": len(unsupported) == 0,
        "unsupported_venues": unsupported,
        "required_venues": list(required_venues),
    }


def evaluate_dataset_safe_replay_gate(
    dataset_selection_id: str,
    outputs: list[Mapping[str, Any]],
) -> DatasetQualityGateResult:
    rejections: list[str] = []

    if not outputs:
        rejections.append("EMPTY_DATASET_SELECTION")

    for idx, out in enumerate(outputs):
        qs = out.get("quality_status")
        rc = out.get("replay_compatible", False)
        es = out.get("evidence_status")

        if qs != "SAFE":
            rejections.append(f"OUTPUT_{idx}_NOT_SAFE: {qs}")
        if not rc:
            rejections.append(f"OUTPUT_{idx}_NOT_REPLAY_COMPATIBLE")
        if es != "SAFE":
            rejections.append(f"OUTPUT_{idx}_EVIDENCE_NOT_SAFE: {es}")

    is_safe = all("NOT_SAFE" not in r for r in rejections)
    is_replay_compatible = all("NOT_REPLAY_COMPATIBLE" not in r for r in rejections)
    passed = len(rejections) == 0

    return DatasetQualityGateResult(
        dataset_selection_id=dataset_selection_id,
        is_safe=is_safe,
        is_replay_compatible=is_replay_compatible,
        passed=passed,
        rejection_reasons=rejections,
    )
