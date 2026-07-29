"""Authoritative strategy scope for the official paper runtime.

Detection and research may continue for every family.  Only the three
families listed as ACTIVE are allowed to create canonical paper-economic
effects.  This module deliberately has no environment-variable override:
changing the economic scope requires a reviewed code change and tests.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum


class StrategyScopeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SHADOW = "SHADOW"
    DISABLED = "DISABLED"
    RESEARCH_ONLY = "RESEARCH_ONLY"


@dataclass(frozen=True, slots=True)
class StrategyScopeEntry:
    family: str
    status: StrategyScopeStatus
    materializes_paper_economics: bool
    reason: str


_SCOPE: tuple[StrategyScopeEntry, ...] = (
    StrategyScopeEntry(
        "cross_venue_dislocation",
        StrategyScopeStatus.ACTIVE,
        True,
        "Executable cross-venue evidence may enter the canonical paper core.",
    ),
    StrategyScopeEntry(
        "lead_lag",
        StrategyScopeStatus.ACTIVE,
        True,
        "Frozen causal lead-lag evidence may enter the canonical paper core.",
    ),
    StrategyScopeEntry(
        "copy_vault",
        StrategyScopeStatus.ACTIVE,
        True,
        "Fresh leader and vault evidence may enter the canonical paper core.",
    ),
    StrategyScopeEntry(
        "twap_metaorder",
        StrategyScopeStatus.SHADOW,
        False,
        "Research probe only until forward evidence and ablation are complete.",
    ),
    StrategyScopeEntry(
        "ofi_microprice",
        StrategyScopeStatus.SHADOW,
        False,
        "Research probe only until forward evidence and ablation are complete.",
    ),
    StrategyScopeEntry(
        "entity_consensus",
        StrategyScopeStatus.SHADOW,
        False,
        "Entity clustering can annotate evidence but cannot create paper PnL.",
    ),
    StrategyScopeEntry(
        "funding_carry",
        StrategyScopeStatus.DISABLED,
        False,
        "Outside the active V2 economic scope; collection remains read-only.",
    ),
    StrategyScopeEntry(
        "triangular_arbitrage",
        StrategyScopeStatus.RESEARCH_ONLY,
        False,
        "Research diagnostics only; no canonical paper execution.",
    ),
    StrategyScopeEntry(
        "market_making",
        StrategyScopeStatus.RESEARCH_ONLY,
        False,
        "Quotes are diagnostics only; queue economics are not yet proven.",
    ),
    StrategyScopeEntry(
        "external_github_profiles",
        StrategyScopeStatus.DISABLED,
        False,
        "The retired GitHub bus cannot be a source of trades or PnL.",
    ),
)

_BY_FAMILY = {entry.family: entry for entry in _SCOPE}


def authoritative_strategy_scope() -> tuple[StrategyScopeEntry, ...]:
    """Return the immutable, reviewable strategy-scope manifest."""

    return _SCOPE


def active_strategy_families() -> frozenset[str]:
    return frozenset(
        entry.family
        for entry in _SCOPE
        if entry.status is StrategyScopeStatus.ACTIVE and entry.materializes_paper_economics
    )


def strategy_can_materialize(family: str) -> bool:
    entry = _BY_FAMILY.get(str(family).strip().lower())
    return bool(
        entry is not None
        and entry.status is StrategyScopeStatus.ACTIVE
        and entry.materializes_paper_economics
    )


def strategy_scope_status(family: str) -> StrategyScopeStatus:
    entry = _BY_FAMILY.get(str(family).strip().lower())
    return entry.status if entry is not None else StrategyScopeStatus.DISABLED


def strategy_scope_refusal(family: str) -> str:
    normalized = str(family).strip().upper() or "UNKNOWN"
    return f"STRATEGY_SCOPE_BLOCKED_{normalized}"


def strategy_scope_payload() -> dict[str, object]:
    return {
        "scope_version": "V2-20260729",
        "active_families": sorted(active_strategy_families()),
        "entries": [
            {
                **asdict(entry),
                "status": entry.status.value,
            }
            for entry in _SCOPE
        ],
        "environment_override_allowed": False,
    }
