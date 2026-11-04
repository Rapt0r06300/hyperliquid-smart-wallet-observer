"""Authoritative strategy scope for the official paper runtime."""
from __future__ import annotations

import os
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
    StrategyScopeEntry("cross_venue_dislocation", StrategyScopeStatus.DISABLED, False,
                       "Paused while AlinaSmartFlow simulations focus on CopyVault only."),
    StrategyScopeEntry("lead_lag", StrategyScopeStatus.DISABLED, False,
                       "Paused while AlinaSmartFlow simulations focus on CopyVault only."),
    StrategyScopeEntry("copy_vault", StrategyScopeStatus.ACTIVE, True,
                       "Fresh leader and vault evidence may enter the canonical paper core."),
    StrategyScopeEntry("twap_metaorder", StrategyScopeStatus.SHADOW, False,
                       "Research probe only until forward evidence and ablation are complete."),
    StrategyScopeEntry("ofi_microprice", StrategyScopeStatus.SHADOW, False,
                       "Research probe only until forward evidence and ablation are complete."),
    StrategyScopeEntry("entity_consensus", StrategyScopeStatus.SHADOW, False,
                       "Entity clustering can annotate evidence but cannot create paper PnL."),
    StrategyScopeEntry("funding_carry", StrategyScopeStatus.DISABLED, False,
                       "Outside the active V2 economic scope; collection remains read-only."),
    StrategyScopeEntry("carry", StrategyScopeStatus.DISABLED, False,
                       "Carry is disabled by scope and cannot create paper intents or PnL."),
    StrategyScopeEntry("triangular_arbitrage", StrategyScopeStatus.RESEARCH_ONLY, False,
                       "Research diagnostics only; no canonical paper execution."),
    StrategyScopeEntry("market_making", StrategyScopeStatus.RESEARCH_ONLY, False,
                       "Quotes are diagnostics only; queue economics are not yet proven."),
    StrategyScopeEntry("external_github_profiles", StrategyScopeStatus.DISABLED, False,
                       "The retired GitHub bus cannot be a source of trades or PnL."),
)

# Versioned naming is accepted only as an input alias; the public scope remains
# one canonical family and never creates a second economic module.
_FAMILY_ALIASES = {"cross_venue_dislocation_v2": "cross_venue_dislocation"}
_BY_FAMILY = {entry.family: entry for entry in _SCOPE}

# Launch-time contract: the official runtime has exactly one paper family.
OFFICIAL_SCOPE_VERSION = "COPY_VAULT_PAPER_V2"
OFFICIAL_SCOPE_FAMILY = "copy_vault"


def canonical_strategy_family(family: str) -> str:
    normalized = str(family).strip().lower()
    return _FAMILY_ALIASES.get(normalized, normalized)


def authoritative_strategy_scope() -> tuple[StrategyScopeEntry, ...]:
    return _SCOPE


def active_strategy_families() -> frozenset[str]:
    return frozenset(
        entry.family for entry in _SCOPE
        if entry.status is StrategyScopeStatus.ACTIVE
        and entry.materializes_paper_economics
    )


def strategy_can_materialize(family: str) -> bool:
    entry = _BY_FAMILY.get(canonical_strategy_family(family))
    return bool(
        entry is not None
        and entry.status is StrategyScopeStatus.ACTIVE
        and entry.materializes_paper_economics
    )


def require_active_strategy(family: str) -> str:
    """Return the canonical active family or fail closed at a simulation boundary."""
    canonical = canonical_strategy_family(family)
    if not strategy_can_materialize(canonical):
        raise ValueError(f"DISABLED_BY_SCOPE:{canonical or 'unknown_family'}")
    return canonical


def strategy_scope_status(family: str) -> StrategyScopeStatus:
    entry = _BY_FAMILY.get(canonical_strategy_family(family))
    return entry.status if entry is not None else StrategyScopeStatus.DISABLED


def strategy_scope_refusal(family: str) -> str:
    normalized = str(family).strip().upper() or "UNKNOWN"
    return f"STRATEGY_SCOPE_BLOCKED_{normalized}"


def strategy_scope_payload() -> dict[str, object]:
    return {
        "scope_version": "V2-20260729",
        "official_scope_version": OFFICIAL_SCOPE_VERSION,
        "official_scope_family": OFFICIAL_SCOPE_FAMILY,
        "active_families": sorted(active_strategy_families()),
        "family_aliases": dict(sorted(_FAMILY_ALIASES.items())),
        "entries": [
            {**asdict(entry), "status": entry.status.value}
            for entry in _SCOPE
        ],
        "environment_override_allowed": False,
    }


def verify_official_runtime_scope(env: dict[str, str] | None = None) -> tuple[bool, tuple[str, ...]]:
    """Reject inherited scope widening at the official process boundary."""
    values = env or {}
    mismatches: list[str] = []
    if active_strategy_families() != frozenset({OFFICIAL_SCOPE_FAMILY}):
        mismatches.append("canonical active family is not exactly copy_vault")
    declared = str(values.get("HYPERSMART_ACTIVE_STRATEGY_SCOPE", "")).strip().lower()
    if declared and declared != OFFICIAL_SCOPE_FAMILY:
        mismatches.append(
            f"HYPERSMART_ACTIVE_STRATEGY_SCOPE={declared!r} (expected {OFFICIAL_SCOPE_FAMILY!r})"
        )
    inherited = str(values.get("HYPERSMART_ACTIVE_STRATEGIES", "")).strip()
    if inherited:
        mismatches.append("HYPERSMART_ACTIVE_STRATEGIES override is forbidden")
    return not mismatches, tuple(mismatches)


def build_official_scope_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """Build a launch environment that cannot widen the official strategy scope."""
    values = dict(os.environ if env is None else env)
    values.pop("HYPERSMART_ACTIVE_STRATEGIES", None)
    values["HYPERSMART_ACTIVE_STRATEGY_SCOPE"] = OFFICIAL_SCOPE_FAMILY
    values["HYPERSMART_SCOPE_OVERRIDE_ALLOWED"] = "0"
    valid, reasons = verify_official_runtime_scope(values)
    if not valid:
        raise ValueError("OFFICIAL_SCOPE_INVALID:" + ",".join(reasons))
    return values


def paper_read_only_scope_receipt(env: dict[str, str] | None = None) -> dict[str, object]:
    values = dict(env or {})
    valid = values.get("PAPER_ONLY") is True and values.get("READ_ONLY") is True and values.get("LIVE_TRADING") is False
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "PAPER_READ_ONLY_ENFORCED" if valid else "PAPER_READ_ONLY_GAP", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def copy_vault_only_receipt(families: tuple[str, ...]) -> dict[str, object]:
    normalized = {canonical_strategy_family(value) for value in families}
    valid = normalized == {OFFICIAL_SCOPE_FAMILY}
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "COPY_VAULT_ONLY" if valid else "SCOPE_WIDENED", "families": sorted(normalized), "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def experimental_flags_receipt(env: dict[str, str] | None = None) -> dict[str, object]:
    values = dict(env or {})
    forbidden = {key: value for key, value in values.items() if key.startswith("HYPERSMART_") and key not in {"HYPERSMART_ACTIVE_STRATEGY_SCOPE"} and str(value).strip()}
    valid = not forbidden
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "EXPERIMENTAL_FLAGS_BOUNDED" if valid else "EXPERIMENTAL_FLAG_PRESENT", "forbidden": sorted(forbidden), "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def fail_closed_scope_receipt(family: str) -> dict[str, object]:
    canonical = canonical_strategy_family(family)
    valid = canonical != OFFICIAL_SCOPE_FAMILY and not strategy_can_materialize(canonical)
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "SCOPE_REFUSES_DISABLED_FAMILY" if valid else "SCOPE_ALLOWS_UNSAFE_FAMILY", "family": canonical, "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def phase_contract_receipt(phase: str, allowed_phases: tuple[str, ...]) -> dict[str, object]:
    valid = phase in allowed_phases
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "PHASE_CONTRACT_VALID" if valid else "PHASE_CONTRACT_INVALID", "phase": phase, "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def lease_epoch_receipt(*, lease_epoch: int, phase_epoch: int, lease_active: bool) -> dict[str, object]:
    valid = isinstance(lease_epoch, int) and isinstance(phase_epoch, int) and lease_epoch == phase_epoch and bool(lease_active)
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "LEASE_EPOCH_BOUND" if valid else "LEASE_EPOCH_MISMATCH", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def continuous_collection_receipt(*, checkpoint_age_ms: int, max_age_ms: int, collection_active: bool) -> dict[str, object]:
    valid = isinstance(checkpoint_age_ms, int) and isinstance(max_age_ms, int) and 0 <= checkpoint_age_ms <= max_age_ms and bool(collection_active)
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "COLLECTION_CONTINUITY_BOUNDED" if valid else "COLLECTION_CONTINUITY_GAP", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def cloud_path_receipt(*, runner_kind: str, self_hosted: bool, local_dependency: bool) -> dict[str, object]:
    valid = runner_kind == "github-hosted" and not bool(self_hosted) and not bool(local_dependency)
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "CLOUD_PATH_AUTHORIZED" if valid else "CLOUD_PATH_UNAUTHORIZED", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


__all__ = [
    "StrategyScopeStatus", "StrategyScopeEntry", "OFFICIAL_SCOPE_VERSION",
    "OFFICIAL_SCOPE_FAMILY", "canonical_strategy_family", "authoritative_strategy_scope",
    "active_strategy_families", "strategy_can_materialize", "require_active_strategy",
    "strategy_scope_status", "strategy_scope_refusal", "strategy_scope_payload",
    "verify_official_runtime_scope", "build_official_scope_environment",
    "paper_read_only_scope_receipt", "copy_vault_only_receipt", "experimental_flags_receipt",
    "fail_closed_scope_receipt", "phase_contract_receipt", "lease_epoch_receipt",
    "continuous_collection_receipt", "cloud_path_receipt",
]
