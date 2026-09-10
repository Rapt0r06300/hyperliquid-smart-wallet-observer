"""Wire serializable Copy-Vault universe evidence into vNext candidate gating."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Any

from hl_observer.backtesting.copy_vault_universe_integrity import (
    evaluate_copy_vault_universe_integrity,
)

SCHEMA_VERSION = "hypersmart.copy_vault_vnext_integrity.v1"


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _correlation_rows(value: object) -> tuple[dict[tuple[str, str], float], bool]:
    if not _is_sequence(value):
        return {}, False
    correlations: dict[tuple[str, str], float] = {}
    valid = True
    for row in value:
        if not isinstance(row, Mapping):
            valid = False
            continue
        left = str(row.get("left") or "").strip().lower()
        right = str(row.get("right") or "").strip().lower()
        try:
            score = float(row.get("correlation"))
        except (TypeError, ValueError, OverflowError):
            valid = False
            continue
        if not isfinite(score):
            valid = False
            continue
        if not left or not right:
            valid = False
            continue
        correlations[(left, right)] = score
    return correlations, valid


def _cohort_rows(value: object) -> tuple[list[Mapping[str, Any]], bool]:
    if not _is_sequence(value):
        return [], False
    rows: list[Mapping[str, Any]] = []
    valid = True
    for row in value:
        if not isinstance(row, Mapping):
            valid = False
            continue
        rows.append(row)
    return rows, valid


def evaluate_copy_vault_vnext_integrity(copy_raw: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = copy_raw.get("universe_integrity") if isinstance(copy_raw, Mapping) else None
    payload = raw if isinstance(raw, Mapping) else {}
    correlations, correlations_valid = _correlation_rows(payload.get("correlations"))
    complete_universe = payload.get("complete_universe")
    observed_survivors = payload.get("observed_survivors")
    cohort, cohort_valid = _cohort_rows(payload.get("cohort"))
    entity_groups = payload.get("entity_groups")

    evidence = evaluate_copy_vault_universe_integrity(
        complete_universe=complete_universe if _is_sequence(complete_universe) else (),
        observed_survivors=observed_survivors if _is_sequence(observed_survivors) else (),
        cohort=cohort,
        correlations=correlations,
        entity_groups=entity_groups if isinstance(entity_groups, Mapping) else {},
    )
    reasons = list(evidence.get("reasons") or [])
    if not isinstance(raw, Mapping):
        reasons.append("UNIVERSE_INTEGRITY_INPUT_MISSING")
    if payload.get("universe_complete") is not True:
        reasons.append("UNIVERSE_COMPLETENESS_UNPROVEN")
    if payload.get("correlations_complete") is not True:
        reasons.append("CORRELATION_COVERAGE_UNPROVEN")
    if not correlations_valid:
        reasons.append("CORRELATION_EVIDENCE_INVALID")
    if not cohort_valid:
        reasons.append("COHORT_EVIDENCE_INVALID")
    reasons = list(dict.fromkeys(str(reason) for reason in reasons))
    return {
        **evidence,
        "schema_version": SCHEMA_VERSION,
        "eligible": not reasons,
        "reasons": reasons,
        "input_present": isinstance(raw, Mapping),
        "universe_complete": payload.get("universe_complete") is True,
        "correlations_complete": payload.get("correlations_complete") is True,
        "paper_read_only": True,
        "real_execution": False,
    }


def gate_copy_vault_candidate(
    candidate: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    gated = dict(candidate)
    gated["universe_integrity"] = dict(evidence)
    if evidence.get("eligible") is not True:
        gated["selection_eligible"] = False
        gated["physical_freeze_allowed"] = False
        gated["freeze_candidate_sha256"] = None
    return gated


__all__ = [
    "SCHEMA_VERSION",
    "evaluate_copy_vault_vnext_integrity",
    "gate_copy_vault_candidate",
]
