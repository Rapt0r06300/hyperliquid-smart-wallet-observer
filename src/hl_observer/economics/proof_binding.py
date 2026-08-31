"""Fail-closed binding between economic assumptions, formulas and PnL evidence."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from .assumptions import (
    EconomicAssumptionRegistry,
    EconomicRunMode,
    MaturityStage,
    hash_payload,
    is_certifiable_mode,
)

ECONOMIC_POLICY_VERSION = "hypersmart.economic_policy.v21"
CONTRACT_SCHEMA = "hypersmart.family_economic_contract.v2"
EVIDENCE_BUNDLE_SCHEMA = "hypersmart.economic_evidence_bundle.v1"
MATURITY_TRANSITION_SCHEMA = "hypersmart.economic_maturity_transition.v1"

REQUIRED_REALITY_COMPONENTS = (
    "fee_treatment",
    "fill_count",
    "funding_treatment",
    "latency_treatment",
    "slippage_capacity_treatment",
    "spread_treatment",
)

_FAMILY_ALIASES = {
    "COPY_VAULT": "COPY_VAULT",
    "LEAD_LAG": "LEAD_LAG",
    "CROSS_VENUE": "CROSS_VENUE",
    "CROSS_VENUE_DISLOCATION": "CROSS_VENUE",
    "CROSS_VENUE_DISLOCATION_V2": "CROSS_VENUE",
}
_MATURITY_ORDER = tuple(MaturityStage)


def canonical_economic_family(value: object) -> str:
    normalized = str(value or "").strip().upper().replace("-", "_")
    return _FAMILY_ALIASES.get(normalized, normalized)


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _safe_hash(payload: object) -> str | None:
    try:
        return hash_payload(payload)
    except (TypeError, ValueError):
        return None


def build_numeric_provenance_pointers(
    registry: EconomicAssumptionRegistry,
    required_ids: Iterable[str],
) -> dict[str, Any]:
    """Return a reconstructible pointer for every scoreboard-critical scalar."""

    pointers: dict[str, Any] = {}
    for assumption_id in sorted(set(required_ids)):
        chain = registry.provenance_chain(assumption_id)
        nodes = []
        for node_id in chain:
            assumption = registry.get(node_id)
            nodes.append(
                {
                    "assumption_id": node_id,
                    "classification": assumption.classification.value,
                    "formula_id": assumption.formula_id,
                    "source_hash": assumption.source_hash,
                    "source_ref": assumption.source_ref,
                    "unit": assumption.unit,
                    "value": assumption.value,
                }
            )
        pointers[assumption_id] = {
            "chain": list(chain),
            "nodes": nodes,
            "terminal_value": registry.get(assumption_id).value,
        }
    return pointers


def build_economic_evidence_bundle(
    *,
    family: str,
    registry: EconomicAssumptionRegistry,
    required_ids: Iterable[str],
    reality_model_version: str,
    reality_model_components: Mapping[str, str],
    run_mode: EconomicRunMode | str,
    maturity_stage: MaturityStage | str = MaturityStage.BUILT,
) -> dict[str, Any]:
    """Freeze one deterministic economic policy bundle for a run or artifact."""

    normalized_family = canonical_economic_family(family)
    normalized_run_mode = EconomicRunMode(str(run_mode).strip().upper())
    stage = MaturityStage(str(maturity_stage).strip().upper())
    required = tuple(sorted(set(required_ids)))
    snapshot = registry.snapshot()
    formulas = list(snapshot["formulas"])
    pointers = build_numeric_provenance_pointers(registry, required)
    components = {
        str(key): str(value)
        for key, value in sorted(reality_model_components.items())
        if str(key) and str(value)
    }
    missing_components = sorted(set(REQUIRED_REALITY_COMPONENTS) - set(components))
    if missing_components:
        raise ValueError(f"reality model incomplet: {missing_components}")
    body = {
        "schema": EVIDENCE_BUNDLE_SCHEMA,
        "policy_version": ECONOMIC_POLICY_VERSION,
        "family": normalized_family,
        "run_mode": normalized_run_mode.value,
        "reality_model_version": str(reality_model_version),
        "reality_model_components": components,
        "reality_model_hash": hash_payload(
            {
                "version": str(reality_model_version),
                "components": components,
            }
        ),
        "assumption_snapshot_hash": hash_payload(snapshot),
        "formula_snapshot_hash": hash_payload(formulas),
        "numeric_provenance_hash": hash_payload(pointers),
        "required_assumption_ids": list(required),
        "maturity_stage": stage.value,
    }
    return {**body, "bundle_hash": hash_payload(body)}


def audit_economic_contract_receipt(
    receipt: object,
    *,
    expected_family: object | None = None,
    require_certifiable_mode: bool = False,
) -> dict[str, Any]:
    """Validate an externally loaded family receipt without trusting its prose."""

    issues: list[str] = []
    if not isinstance(receipt, Mapping):
        return {
            "ready": False,
            "issues": ["ECONOMIC_CONTRACT_MISSING"],
            "family": canonical_economic_family(expected_family),
        }

    family = canonical_economic_family(receipt.get("family"))
    expected = canonical_economic_family(expected_family) if expected_family is not None else family
    if receipt.get("schema") != CONTRACT_SCHEMA:
        issues.append("ECONOMIC_CONTRACT_SCHEMA_INVALID")
    if not family or family != expected:
        issues.append("ECONOMIC_CONTRACT_FAMILY_MISMATCH")
    if receipt.get("policy_version") != ECONOMIC_POLICY_VERSION:
        issues.append("ECONOMIC_POLICY_VERSION_MISMATCH")
    try:
        run_mode = EconomicRunMode(str(receipt.get("run_mode") or ""))
    except ValueError:
        run_mode = None
        issues.append("ECONOMIC_RUN_MODE_INVALID")
    if (
        require_certifiable_mode
        and run_mode is not None
        and not is_certifiable_mode(run_mode)
    ):
        issues.append("ECONOMIC_RUN_MODE_NOT_CERTIFIABLE")

    snapshot = receipt.get("assumption_snapshot")
    formulas = receipt.get("formula_manifest")
    pointers = receipt.get("numeric_provenance_pointers")
    snapshot_hash = _safe_hash(snapshot)
    formula_hash = _safe_hash(formulas)
    provenance_hash = _safe_hash(pointers)
    if snapshot_hash is None or snapshot_hash != receipt.get("assumption_snapshot_hash"):
        issues.append("ASSUMPTION_SNAPSHOT_HASH_MISMATCH")
    if formula_hash is None or formula_hash != receipt.get("formula_snapshot_hash"):
        issues.append("FORMULA_SNAPSHOT_HASH_MISMATCH")
    if provenance_hash is None or provenance_hash != receipt.get("numeric_provenance_hash"):
        issues.append("NUMERIC_PROVENANCE_HASH_MISMATCH")

    certification = receipt.get("certification")
    if not isinstance(certification, Mapping) or certification.get("ready") is not True:
        issues.append("ECONOMIC_CERTIFICATION_NOT_READY")
    elif certification.get("assumption_snapshot_hash") != snapshot_hash:
        issues.append("CERTIFICATION_SNAPSHOT_HASH_MISMATCH")

    required = receipt.get("required_assumption_ids")
    values = receipt.get("values")
    required_ids = (
        [str(item) for item in required]
        if isinstance(required, list) and all(isinstance(item, str) for item in required)
        else []
    )
    if not required_ids or required_ids != sorted(set(required_ids)):
        issues.append("REQUIRED_ASSUMPTION_IDS_INVALID")
    if not isinstance(values, Mapping) or set(values) != set(required_ids):
        issues.append("ECONOMIC_VALUES_COVERAGE_MISMATCH")
    if not isinstance(pointers, Mapping) or set(pointers) != set(required_ids):
        issues.append("NUMERIC_PROVENANCE_COVERAGE_MISMATCH")
    elif isinstance(values, Mapping):
        for assumption_id in required_ids:
            pointer = pointers.get(assumption_id)
            if not isinstance(pointer, Mapping):
                issues.append(f"NUMERIC_PROVENANCE_POINTER_INVALID:{assumption_id}")
                continue
            chain = pointer.get("chain")
            nodes = pointer.get("nodes")
            node_ids = (
                [str(node.get("assumption_id")) for node in nodes]
                if isinstance(nodes, list) and all(isinstance(node, Mapping) for node in nodes)
                else []
            )
            if (
                not isinstance(chain, list)
                or not chain
                or chain[-1] != assumption_id
                or node_ids != chain
                or pointer.get("terminal_value") != values.get(assumption_id)
            ):
                issues.append(f"NUMERIC_PROVENANCE_POINTER_INVALID:{assumption_id}")
                continue
            if any(not _is_sha256(node.get("source_hash")) for node in nodes):
                issues.append(f"NUMERIC_PROVENANCE_SOURCE_HASH_INVALID:{assumption_id}")

    components = receipt.get("reality_model_components")
    if not isinstance(components, Mapping):
        issues.append("REALITY_MODEL_COMPONENTS_MISSING")
        components = {}
    else:
        missing = sorted(set(REQUIRED_REALITY_COMPONENTS) - set(components))
        if missing or any(not str(components[key]) for key in REQUIRED_REALITY_COMPONENTS):
            issues.append("REALITY_MODEL_COMPONENTS_INCOMPLETE")
    reality_hash = _safe_hash(
        {
            "version": str(receipt.get("reality_model_version") or ""),
            "components": dict(components),
        }
    )
    if reality_hash != receipt.get("reality_model_hash"):
        issues.append("REALITY_MODEL_HASH_MISMATCH")

    bundle = receipt.get("economic_evidence_bundle")
    if not isinstance(bundle, Mapping):
        issues.append("ECONOMIC_EVIDENCE_BUNDLE_MISSING")
        bundle = {}
    else:
        bundle_body = {key: value for key, value in bundle.items() if key != "bundle_hash"}
        if _safe_hash(bundle_body) != bundle.get("bundle_hash"):
            issues.append("ECONOMIC_EVIDENCE_BUNDLE_HASH_MISMATCH")
    expected_bundle_fields = {
        "schema": EVIDENCE_BUNDLE_SCHEMA,
        "policy_version": ECONOMIC_POLICY_VERSION,
        "family": family,
        "run_mode": run_mode.value if run_mode is not None else None,
        "reality_model_version": receipt.get("reality_model_version"),
        "reality_model_components": dict(components),
        "reality_model_hash": receipt.get("reality_model_hash"),
        "assumption_snapshot_hash": snapshot_hash,
        "formula_snapshot_hash": formula_hash,
        "numeric_provenance_hash": provenance_hash,
        "required_assumption_ids": required_ids,
        "maturity_stage": MaturityStage.BUILT.value,
    }
    for key, expected_value in expected_bundle_fields.items():
        if bundle.get(key) != expected_value:
            issues.append(f"ECONOMIC_EVIDENCE_BUNDLE_FIELD_MISMATCH:{key}")

    return {
        "ready": not issues,
        "issues": list(dict.fromkeys(issues)),
        "family": family,
        "policy_version": receipt.get("policy_version"),
        "run_mode": run_mode.value if run_mode is not None else None,
        "assumption_snapshot_hash": snapshot_hash,
        "formula_snapshot_hash": formula_hash,
        "numeric_provenance_hash": provenance_hash,
        "reality_model_hash": reality_hash,
        "bundle_hash": bundle.get("bundle_hash"),
    }


def build_maturity_transition(
    *,
    family: str,
    from_stage: MaturityStage | str,
    to_stage: MaturityStage | str,
    evidence_refs: Iterable[str],
    previous_transition_hash: str | None = None,
) -> dict[str, Any]:
    """Create one adjacent, evidence-backed maturity transition."""

    source = MaturityStage(str(from_stage).strip().upper())
    target = MaturityStage(str(to_stage).strip().upper())
    if _MATURITY_ORDER.index(target) != _MATURITY_ORDER.index(source) + 1:
        raise ValueError(f"maturity transition non adjacente: {source.value}->{target.value}")
    references = tuple(sorted({str(item).strip() for item in evidence_refs if str(item).strip()}))
    if not references:
        raise ValueError("evidence_refs requis pour une transition de maturite")
    if source is not MaturityStage.BUILT and not _is_sha256(previous_transition_hash):
        raise ValueError("previous_transition_hash requis apres BUILT")
    body = {
        "schema": MATURITY_TRANSITION_SCHEMA,
        "family": canonical_economic_family(family),
        "from_stage": source.value,
        "to_stage": target.value,
        "evidence_refs": list(references),
        "previous_transition_hash": previous_transition_hash,
    }
    return {**body, "transition_hash": hash_payload(body)}


def audit_maturity_chain(
    family: str,
    transitions: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Prove a maturity stage only from a complete linked transition chain."""

    expected_family = canonical_economic_family(family)
    current = MaturityStage.BUILT
    previous_hash: str | None = None
    issues: list[str] = []
    count = 0
    for count, transition in enumerate(transitions, start=1):
        body = {key: value for key, value in transition.items() if key != "transition_hash"}
        if transition.get("schema") != MATURITY_TRANSITION_SCHEMA:
            issues.append(f"MATURITY_SCHEMA_INVALID:{count}")
        if canonical_economic_family(transition.get("family")) != expected_family:
            issues.append(f"MATURITY_FAMILY_MISMATCH:{count}")
        if _safe_hash(body) != transition.get("transition_hash"):
            issues.append(f"MATURITY_HASH_MISMATCH:{count}")
        if transition.get("from_stage") != current.value:
            issues.append(f"MATURITY_SOURCE_STAGE_MISMATCH:{count}")
            break
        if transition.get("previous_transition_hash") != previous_hash:
            issues.append(f"MATURITY_PREVIOUS_HASH_MISMATCH:{count}")
        try:
            target = MaturityStage(str(transition.get("to_stage")))
        except ValueError:
            issues.append(f"MATURITY_TARGET_STAGE_INVALID:{count}")
            break
        if _MATURITY_ORDER.index(target) != _MATURITY_ORDER.index(current) + 1:
            issues.append(f"MATURITY_STAGE_SKIP:{count}")
            break
        refs = transition.get("evidence_refs")
        if not isinstance(refs, list) or not refs or any(not str(item).strip() for item in refs):
            issues.append(f"MATURITY_EVIDENCE_MISSING:{count}")
        current = target
        previous_hash = str(transition.get("transition_hash") or "")
    return {
        "ready": not issues,
        "issues": issues,
        "family": expected_family,
        "stage": current.value,
        "transition_count": count,
        "last_transition_hash": previous_hash,
    }


def audit_cross_artifact_numeric_consistency(
    *,
    authority_name: str,
    authority_values: Mapping[str, object],
    artifacts: Mapping[str, Mapping[str, object]],
    fields: Iterable[str],
    tolerance: float = 1e-8,
) -> dict[str, Any]:
    """Compare shared scalars to one authority; never recompute PnL report-side."""

    issues: list[str] = []
    normalized_fields = tuple(sorted(set(fields)))
    for field in normalized_fields:
        authority = authority_values.get(field)
        try:
            authority_number = float(authority)
        except (TypeError, ValueError, OverflowError):
            issues.append(f"AUTHORITY_VALUE_UNMEASURED:{field}")
            continue
        if not math.isfinite(authority_number):
            issues.append(f"AUTHORITY_VALUE_UNMEASURED:{field}")
            continue
        for artifact_name, values in sorted(artifacts.items()):
            try:
                candidate = float(values.get(field))
            except (TypeError, ValueError, OverflowError):
                issues.append(f"ARTIFACT_VALUE_UNMEASURED:{artifact_name}:{field}")
                continue
            if not math.isfinite(candidate) or not math.isclose(
                candidate, authority_number, abs_tol=tolerance
            ):
                issues.append(f"ARTIFACT_VALUE_MISMATCH:{artifact_name}:{field}")
    receipt_body = {
        "schema": "hypersmart.cross_artifact_numeric_consistency.v1",
        "authority_name": str(authority_name),
        "authority_values_hash": hash_payload(dict(authority_values)),
        "artifact_hashes": {
            name: hash_payload(dict(values)) for name, values in sorted(artifacts.items())
        },
        "fields": list(normalized_fields),
        "tolerance": float(tolerance),
    }
    return {
        **receipt_body,
        "ready": not issues,
        "issues": issues,
        "receipt_hash": hash_payload(receipt_body),
    }


__all__ = [
    "CONTRACT_SCHEMA",
    "ECONOMIC_POLICY_VERSION",
    "EVIDENCE_BUNDLE_SCHEMA",
    "MATURITY_TRANSITION_SCHEMA",
    "REQUIRED_REALITY_COMPONENTS",
    "audit_cross_artifact_numeric_consistency",
    "audit_economic_contract_receipt",
    "audit_maturity_chain",
    "build_economic_evidence_bundle",
    "build_maturity_transition",
    "build_numeric_provenance_pointers",
    "canonical_economic_family",
]
