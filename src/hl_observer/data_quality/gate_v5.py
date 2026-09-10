"""V5 §6.5 campaign data-quality gate.

Evidence quality only: this module never authorizes real execution or strategy scope.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DataQualityState(StrEnum):
    PASS = "PASS"
    BLIND = "BLIND"
    CONFLICTED = "CONFLICTED"
    INCOMPLETE = "INCOMPLETE"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class DataQualityInput:
    completeness: float | None
    freshness_ms: int | None
    max_freshness_ms: int
    clock_skew_ms: float | None
    max_clock_skew_ms: float
    schema_valid: bool | None
    duplicate_count: int | None
    gap_count: int | None
    symbol_mapping_valid: bool | None
    source_provenance_present: bool
    days_covered: int | None
    min_days_covered: int
    coins_covered: int | None
    min_coins_covered: int
    wallets_vaults_covered: int | None
    min_wallets_vaults_covered: int


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    state: DataQualityState
    reasons: tuple[str, ...]
    tradeable: bool


def evaluate_campaign_data_quality(value: DataQualityInput) -> DataQualityReport:
    """Unknown stays unknown; stricter states dominate weaker insufficiency."""
    blind: list[str] = []
    conflicted: list[str] = []
    incomplete: list[str] = []
    stale: list[str] = []

    required_known = {
        "completeness": value.completeness,
        "freshness_ms": value.freshness_ms,
        "clock_skew_ms": value.clock_skew_ms,
        "schema_valid": value.schema_valid,
        "duplicate_count": value.duplicate_count,
        "gap_count": value.gap_count,
        "symbol_mapping_valid": value.symbol_mapping_valid,
        "days_covered": value.days_covered,
        "coins_covered": value.coins_covered,
        "wallets_vaults_covered": value.wallets_vaults_covered,
    }
    blind.extend(
        f"MISSING_{name.upper()}" for name, item in required_known.items() if item is None
    )
    if not value.source_provenance_present:
        blind.append("MISSING_SOURCE_PROVENANCE")

    if value.schema_valid is False:
        conflicted.append("SCHEMA_INVALID")
    if value.symbol_mapping_valid is False:
        conflicted.append("SYMBOL_MAPPING_INVALID")
    if value.clock_skew_ms is not None and abs(value.clock_skew_ms) > value.max_clock_skew_ms:
        conflicted.append("CLOCK_SKEW_EXCEEDED")
    if value.duplicate_count is not None and value.duplicate_count > 0:
        conflicted.append("DUPLICATES_PRESENT")
    if value.gap_count is not None and value.gap_count > 0:
        conflicted.append("SEQUENCE_GAPS_PRESENT")

    if value.completeness is not None:
        if not 0.0 <= value.completeness <= 1.0:
            conflicted.append("COMPLETENESS_OUT_OF_RANGE")
        elif value.completeness < 1.0:
            incomplete.append("COMPLETENESS_BELOW_ONE")

    for name, actual, required in (
        ("DAYS", value.days_covered, value.min_days_covered),
        ("COINS", value.coins_covered, value.min_coins_covered),
        ("WALLETS_VAULTS", value.wallets_vaults_covered, value.min_wallets_vaults_covered),
    ):
        if actual is not None and actual < required:
            incomplete.append(f"{name}_COVERAGE_INSUFFICIENT")

    if value.freshness_ms is not None:
        if value.freshness_ms < 0:
            conflicted.append("NEGATIVE_FRESHNESS_CLOCK_ERROR")
        elif value.freshness_ms > value.max_freshness_ms:
            stale.append("FRESHNESS_THRESHOLD_EXCEEDED")

    if blind:
        return DataQualityReport(DataQualityState.BLIND, tuple(sorted(set(blind))), False)
    if conflicted:
        return DataQualityReport(DataQualityState.CONFLICTED, tuple(sorted(set(conflicted))), False)
    if stale:
        return DataQualityReport(DataQualityState.STALE, tuple(sorted(set(stale))), False)
    if incomplete:
        return DataQualityReport(DataQualityState.INCOMPLETE, tuple(sorted(set(incomplete))), False)
    return DataQualityReport(DataQualityState.PASS, (), True)


__all__ = [
    "DataQualityInput",
    "DataQualityReport",
    "DataQualityState",
    "evaluate_campaign_data_quality",
]
