"""Wire serializable Copy-Vault universe evidence into vNext candidate gating."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Any

from hl_observer.backtesting.copy_vault_universe_integrity import (
    evaluate_copy_vault_universe_integrity,
)
from hl_observer.research.wallet_fingerprint import entites_communes, fingerprint

SCHEMA_VERSION = "hypersmart.copy_vault_vnext_integrity.v1"


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _wallet(value: object) -> str:
    return str(value or "").strip().lower()


def _correlation_rows(value: object) -> tuple[dict[tuple[str, str], float], bool]:
    if not _is_sequence(value):
        return {}, False
    correlations: dict[tuple[str, str], float] = {}
    valid = True
    for row in value:
        if not isinstance(row, Mapping):
            valid = False
            continue
        left = _wallet(row.get("left"))
        right = _wallet(row.get("right"))
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


def _behavioral_fingerprint_evidence(
    payload: Mapping[str, Any],
    entity_groups: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    raw = payload.get("behavioral_fingerprint")
    if raw is None:
        return {
            "present": False,
            "complete": False,
            "related_wallet_groups": [],
            "unresolved_related_groups": [],
        }, []
    if not isinstance(raw, Mapping):
        return {
            "present": True,
            "complete": False,
            "related_wallet_groups": [],
            "unresolved_related_groups": [],
        }, ["BEHAVIORAL_FINGERPRINT_EVIDENCE_INVALID"]

    reasons: list[str] = []
    if raw.get("complete") is not True:
        reasons.append("BEHAVIORAL_FINGERPRINT_COVERAGE_UNPROVEN")

    wallet_fills = raw.get("wallet_fills")
    normalized_fills: dict[str, list[Mapping[str, Any]]] = {}
    valid = isinstance(wallet_fills, Mapping)
    if isinstance(wallet_fills, Mapping):
        for wallet, fills in wallet_fills.items():
            normalized_wallet = _wallet(wallet)
            if not normalized_wallet or not _is_sequence(fills):
                valid = False
                continue
            rows: list[Mapping[str, Any]] = []
            for row in fills:
                if not isinstance(row, Mapping):
                    valid = False
                    continue
                rows.append(row)
            normalized_fills[normalized_wallet] = rows
    if not valid:
        reasons.append("BEHAVIORAL_FINGERPRINT_EVIDENCE_INVALID")

    universe = {
        _wallet(wallet)
        for wallet in payload.get("complete_universe", ())
        if _wallet(wallet)
    } if _is_sequence(payload.get("complete_universe")) else set()
    if raw.get("complete") is True and set(normalized_fills) != universe:
        reasons.append("BEHAVIORAL_FINGERPRINT_COVERAGE_INCOMPLETE")

    fingerprints = {wallet: fingerprint(fills) for wallet, fills in normalized_fills.items()}
    related_groups = entites_communes(fingerprints)
    groups = {
        _wallet(wallet): str(group or "").strip()
        for wallet, group in entity_groups.items()
        if _wallet(wallet)
    }
    unresolved: list[list[str]] = []
    for related in related_groups:
        declared = {groups.get(wallet, "") for wallet in related}
        if "" in declared or len(declared) != 1:
            unresolved.append(list(related))
    if unresolved:
        reasons.append("BEHAVIORAL_ENTITY_NORMALIZATION_MISSING")

    return {
        "present": True,
        "complete": raw.get("complete") is True,
        "wallets_fingerprinted": sorted(normalized_fills),
        "fingerprints": fingerprints,
        "related_wallet_groups": related_groups,
        "unresolved_related_groups": unresolved,
    }, reasons


def evaluate_copy_vault_vnext_integrity(copy_raw: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = copy_raw.get("universe_integrity") if isinstance(copy_raw, Mapping) else None
    payload = raw if isinstance(raw, Mapping) else {}
    correlations, correlations_valid = _correlation_rows(payload.get("correlations"))
    complete_universe = payload.get("complete_universe")
    observed_survivors = payload.get("observed_survivors")
    cohort, cohort_valid = _cohort_rows(payload.get("cohort"))
    entity_groups = payload.get("entity_groups")
    normalized_entity_groups = entity_groups if isinstance(entity_groups, Mapping) else {}

    evidence = evaluate_copy_vault_universe_integrity(
        complete_universe=complete_universe if _is_sequence(complete_universe) else (),
        observed_survivors=observed_survivors if _is_sequence(observed_survivors) else (),
        cohort=cohort,
        correlations=correlations,
        entity_groups=normalized_entity_groups,
    )
    behavioral, behavioral_reasons = _behavioral_fingerprint_evidence(
        payload,
        normalized_entity_groups,
    )
    reasons = list(evidence.get("reasons") or [])
    reasons.extend(behavioral_reasons)
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
        "behavioral_fingerprint": behavioral,
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
