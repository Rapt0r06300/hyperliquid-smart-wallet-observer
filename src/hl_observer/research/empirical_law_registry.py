"""P0-120 machine-readable registry for measured laws.

Measured laws are empirical memory, never ACTIVE_SCOPE authority. Historical laws with
missing immutable evidence remain in the registry but are downgraded rather than trusted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Iterable

from hl_observer.research.empirical_memory import (
    EmpiricalEvidence,
    EmpiricalEvidenceState,
    evidence_state,
)

EMPIRICAL_LAW_REGISTRY_IS_ACTIVE_SCOPE_AUTHORITY = False


class EvidenceQuality(StrEnum):
    REVALIDATED = "REVALIDATED"
    STALE = "STALE"
    HISTORICAL_UNVERIFIED = "HISTORICAL_UNVERIFIED"


@dataclass(frozen=True, slots=True)
class EmpiricalLawRecord:
    law_id: str
    hypothesis_family: str
    verdict: str
    measured_value: str
    measured_at: str
    dataset_id: str | None
    dataset_hash: str | None
    experiment_id: str | None
    git_sha: str | None
    cost_model_id: str | None
    source_refs: tuple[str, ...]
    source_hashes: tuple[str, ...]
    evidence_quality: EvidenceQuality
    last_verified: date | None
    retest_after: date | None
    invalidated_if: tuple[str, ...]
    condition_de_reouverture: str
    scope_status_at_measurement: str
    active_scope_authority: bool = False


def _text(law: object, name: str) -> str | None:
    value = str(getattr(law, name, "") or "").strip()
    return value or None


def _evidence(law: object) -> tuple[EmpiricalEvidence, ...]:
    value = getattr(law, "evidence", ())
    if not isinstance(value, tuple):
        return ()
    if not all(isinstance(item, EmpiricalEvidence) for item in value):
        return ()
    return value


def _family(law_id: str) -> str:
    value = law_id.lower()
    if value.startswith("copy_"):
        return "copy_vault"
    if value in {"lead_lag", "cross_venue_leadlag_taker_no_edge"}:
        return "lead_lag"
    if value.startswith(("arb_", "arbitrage_")):
        return "cross_venue_dislocation"
    if value.startswith(("carry_", "funding_")) or value in {
        "hlp_benchmark",
        "zscore_au_plancher",
    }:
        return "funding_carry"
    if value in {"market_making_spread", "spread_prix_du_risque"}:
        return "market_making"
    return "cross_cutting"


def build_record(law: object, *, as_of: date | None = None) -> EmpiricalLawRecord:
    """Build a V5 provenance record without fabricating missing historical metadata."""

    reference_date = as_of or date.today()
    evidence = _evidence(law)
    state = evidence_state(law, as_of=reference_date)
    quality = {
        EmpiricalEvidenceState.REVALIDATED: EvidenceQuality.REVALIDATED,
        EmpiricalEvidenceState.STALE: EvidenceQuality.STALE,
        EmpiricalEvidenceState.UNVERIFIABLE: EvidenceQuality.HISTORICAL_UNVERIFIED,
    }[state]

    structurally_valid = tuple(
        item for item in evidence if item.is_structurally_verifiable(as_of=reference_date)
    )
    legacy_ref = _text(law, "ou_verifier")
    source_refs = tuple(item.uri for item in evidence)
    if not source_refs and legacy_ref:
        source_refs = (legacy_ref,)
    source_hashes = tuple(item.sha256.lower() for item in structurally_valid)
    last_verified = max((item.revalidated_on for item in structurally_valid), default=None)
    retest_after = min(
        (item.revalidated_on + timedelta(days=item.max_age_days) for item in structurally_valid),
        default=None,
    )

    law_id = _text(law, "cle") or ""
    dataset_id = _text(law, "dataset_id")
    dataset_hash = _text(law, "dataset_hash")
    if dataset_id is None and len(structurally_valid) == 1:
        dataset_id = structurally_valid[0].uri
    if dataset_hash is None and len(source_hashes) == 1:
        dataset_hash = source_hashes[0]

    invalidated_raw = getattr(law, "invalidated_if", ())
    invalidated_if = (
        tuple(str(item).strip() for item in invalidated_raw if str(item).strip())
        if isinstance(invalidated_raw, tuple)
        else ()
    )

    return EmpiricalLawRecord(
        law_id=law_id,
        hypothesis_family=_text(law, "hypothesis_family") or _family(law_id),
        verdict=_text(law, "verdict") or "",
        measured_value=_text(law, "chiffre") or "",
        measured_at=_text(law, "date") or "",
        dataset_id=dataset_id,
        dataset_hash=dataset_hash,
        experiment_id=_text(law, "experiment_id"),
        git_sha=_text(law, "git_sha"),
        cost_model_id=_text(law, "cost_model_id"),
        source_refs=source_refs,
        source_hashes=source_hashes,
        evidence_quality=quality,
        last_verified=last_verified,
        retest_after=retest_after,
        invalidated_if=invalidated_if,
        condition_de_reouverture=_text(law, "condition_de_reouverture") or "",
        scope_status_at_measurement=(
            _text(law, "scope_status_at_measurement") or "UNKNOWN_HISTORICAL"
        ),
        active_scope_authority=False,
    )


def build_registry(
    laws: Iterable[object], *, as_of: date | None = None
) -> tuple[EmpiricalLawRecord, ...]:
    return tuple(build_record(law, as_of=as_of) for law in laws)


def failed_hypothesis_ids(laws: Iterable[object]) -> frozenset[str]:
    """Keep rejected hypotheses visible for later multiple-testing accounting."""

    result: set[str] = set()
    for law in laws:
        if (_text(law, "verdict") or "").upper() != "REFUTE":
            continue
        key = _text(law, "cle")
        if key:
            result.add(key)
    return frozenset(result)


def negative_law_reopen_allowed(
    law: object,
    *,
    retest_condition_triggered: bool,
    new_data_available: bool = False,
    new_physical_mechanism: bool = False,
) -> bool:
    """V5 gate: trigger AND new information/mechanism are both mandatory."""

    if (_text(law, "verdict") or "").upper() != "REFUTE":
        return False
    condition = (_text(law, "condition_de_reouverture") or "").lower()
    if not condition or condition.startswith("aucune") or condition.startswith("jamais"):
        return False
    return bool(
        retest_condition_triggered and (new_data_available or new_physical_mechanism)
    )


__all__ = [
    "EMPIRICAL_LAW_REGISTRY_IS_ACTIVE_SCOPE_AUTHORITY",
    "EmpiricalLawRecord",
    "EvidenceQuality",
    "build_record",
    "build_registry",
    "failed_hypothesis_ids",
    "negative_law_reopen_allowed",
]
