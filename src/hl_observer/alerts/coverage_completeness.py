"""Conservative completeness reports for an explicit source universe.

Allocation percentages express research priority only. They never prove that a
source universe is complete. Submitted counts and receipt references remain
unverified declarations until artifact-backed measurement is integrated.
This module therefore preserves ``COVERAGE_UNKNOWN``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any

from hl_observer.alerts.coverage import COVERAGE_RECEIPT_SCHEMA

COMPLETENESS_ATTESTATION_SCHEMA = "hypersmart.coverage_completeness_attestation.v1"
COMPLETENESS_EVIDENCE_KINDS = frozenset(
    {"MEASURED_RECALL_PROXY", "SOURCE_UNIVERSE_RECEIPT"}
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CoverageCompletenessError(ValueError):
    """Raised when evidence cannot safely support a coverage statement."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _text(value: object, *, field: str, maximum: int = 1_000) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise CoverageCompletenessError(f"COMPLETENESS_TEXT_INVALID:{field}")
    return normalized


def _integer(value: object, *, field: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise CoverageCompletenessError(f"COMPLETENESS_INTEGER_INVALID:{field}")
    return value


def _evidence_refs(value: object) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > 128:
        raise CoverageCompletenessError("COMPLETENESS_EVIDENCE_REFS_INVALID")
    refs = [_text(item, field="evidence_ref", maximum=500) for item in value]
    if len(set(refs)) != len(refs):
        raise CoverageCompletenessError("COMPLETENESS_EVIDENCE_REFS_DUPLICATE")
    return sorted(refs)


def _validate_coverage_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(receipt)
    if normalized.get("schema_version") != COVERAGE_RECEIPT_SCHEMA:
        raise CoverageCompletenessError("SOURCE_COVERAGE_RECEIPT_SCHEMA_INVALID")
    supplied_hash = str(normalized.pop("receipt_hash", ""))
    if not _SHA256_RE.fullmatch(supplied_hash) or supplied_hash != _hash(normalized):
        raise CoverageCompletenessError("SOURCE_COVERAGE_RECEIPT_HASH_INVALID")
    if normalized.get("paper_read_only") is not True:
        raise CoverageCompletenessError("COMPLETENESS_PAPER_READ_ONLY_REQUIRED")
    if normalized.get("real_execution") is not False:
        raise CoverageCompletenessError("COMPLETENESS_REAL_EXECUTION_FORBIDDEN")
    universe_hash = str(normalized.get("universe_hash") or "")
    if not _SHA256_RE.fullmatch(universe_hash):
        raise CoverageCompletenessError("SOURCE_UNIVERSE_HASH_INVALID")
    classes = normalized.get("coverage_classes")
    if not isinstance(classes, list) or not classes:
        raise CoverageCompletenessError("SOURCE_COVERAGE_CLASSES_INVALID")
    return {**normalized, "receipt_hash": supplied_hash}


def _normalize_allocation(
    allocation_percent: Mapping[str, object] | None,
    *,
    class_ids: set[str],
) -> dict[str, Any]:
    if allocation_percent is None:
        allocation_percent = {}
    if not isinstance(allocation_percent, Mapping):
        raise CoverageCompletenessError("COVERAGE_ALLOCATION_NOT_MAPPING")
    unknown = sorted(set(map(str, allocation_percent)) - class_ids)
    if unknown:
        raise CoverageCompletenessError(
            "COVERAGE_ALLOCATION_CLASS_UNKNOWN:" + ",".join(unknown)
        )
    normalized: dict[str, float] = {}
    for class_id, raw_value in allocation_percent.items():
        if isinstance(raw_value, bool):
            raise CoverageCompletenessError(
                f"COVERAGE_ALLOCATION_INVALID:{class_id}"
            )
        try:
            value = float(raw_value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise CoverageCompletenessError(
                f"COVERAGE_ALLOCATION_INVALID:{class_id}"
            ) from exc
        if not math.isfinite(value) or not 0.0 <= value <= 100.0:
            raise CoverageCompletenessError(
                f"COVERAGE_ALLOCATION_INVALID:{class_id}"
            )
        normalized[str(class_id)] = round(value, 6)
    total = round(sum(normalized.values()), 6)
    if total > 100.0:
        raise CoverageCompletenessError("COVERAGE_ALLOCATION_TOTAL_EXCEEDS_100")
    return {
        "percent_by_class": dict(sorted(normalized.items())),
        "total_percent": total,
        "semantics": "CONFIGURATION_ONLY_NOT_COMPLETENESS_EVIDENCE",
    }


def _normalize_evidence(
    evidence: Mapping[str, Any],
    *,
    universe_hash: str,
    evaluated_at_ms: int,
) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(evidence, Mapping):
        raise CoverageCompletenessError("COMPLETENESS_EVIDENCE_NOT_MAPPING")
    kind = _text(evidence.get("kind"), field="kind").upper()
    if kind not in COMPLETENESS_EVIDENCE_KINDS:
        raise CoverageCompletenessError("COMPLETENESS_EVIDENCE_KIND_INVALID")
    if evidence.get("universe_hash") != universe_hash:
        raise CoverageCompletenessError("COMPLETENESS_UNIVERSE_BINDING_MISMATCH")
    measured_at_ms = _integer(evidence.get("measured_at_ms"), field="measured_at_ms")
    valid_for_ms = _integer(
        evidence.get("valid_for_ms"), field="valid_for_ms", minimum=1
    )
    if measured_at_ms > evaluated_at_ms:
        raise CoverageCompletenessError("COMPLETENESS_EVIDENCE_FROM_FUTURE")
    normalized: dict[str, Any] = {
        "kind": kind,
        "universe_hash": universe_hash,
        "measured_at_ms": measured_at_ms,
        "valid_for_ms": valid_for_ms,
        "age_ms": evaluated_at_ms - measured_at_ms,
        "method": _text(evidence.get("method"), field="method"),
        "evidence_refs": _evidence_refs(evidence.get("evidence_refs")),
    }
    rejection_reasons: list[str] = []
    if normalized["age_ms"] > valid_for_ms:
        rejection_reasons.append("COMPLETENESS_EVIDENCE_STALE")

    if kind == "MEASURED_RECALL_PROXY":
        relevant_events = _integer(
            evidence.get("relevant_events"), field="relevant_events", minimum=1
        )
        detected_events = _integer(
            evidence.get("detected_events"), field="detected_events"
        )
        if detected_events > relevant_events:
            raise CoverageCompletenessError("RECALL_PROXY_DETECTED_EXCEEDS_RELEVANT")
        normalized.update(
            {
                "sample_definition": _text(
                    evidence.get("sample_definition"), field="sample_definition"
                ),
                "relevant_events": relevant_events,
                "detected_events": detected_events,
                "reported_recall": round(detected_events / relevant_events, 6),
            }
        )
    else:
        receipt_hash = str(evidence.get("authoritative_receipt_hash") or "")
        if not _SHA256_RE.fullmatch(receipt_hash):
            raise CoverageCompletenessError("AUTHORITATIVE_RECEIPT_HASH_INVALID")
        declared_sources = _integer(
            evidence.get("declared_sources"), field="declared_sources", minimum=1
        )
        observed_sources = _integer(
            evidence.get("observed_sources"), field="observed_sources"
        )
        if observed_sources > declared_sources:
            raise CoverageCompletenessError(
                "SOURCE_UNIVERSE_OBSERVED_EXCEEDS_DECLARED"
            )
        normalized.update(
            {
                "authority": _text(evidence.get("authority"), field="authority"),
                "scope": _text(evidence.get("scope"), field="scope"),
                "authoritative_receipt_hash": receipt_hash,
                "declared_sources": declared_sources,
                "observed_sources": observed_sources,
                "reported_observed_ratio": round(observed_sources / declared_sources, 6),
            }
        )
    # A digest binds submitted bytes, not their truth or the referenced artifacts.
    normalized["verification_state"] = "DECLARED_NOT_VERIFIED"
    rejection_reasons.append("COMPLETENESS_EVIDENCE_UNVERIFIED")
    normalized["evidence_hash"] = _hash(normalized)
    return normalized, rejection_reasons


def build_coverage_completeness_attestation(
    coverage_receipt: Mapping[str, Any],
    *,
    evaluated_at_ms: int,
    allocation_percent: Mapping[str, object] | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Retain declared evidence without promoting it to empirical proof."""

    evaluated_at_ms = _integer(evaluated_at_ms, field="evaluated_at_ms")
    receipt = _validate_coverage_receipt(coverage_receipt)
    receipt_time = _integer(receipt.get("evaluated_at_ms"), field="receipt_evaluated_at_ms")
    if receipt_time > evaluated_at_ms:
        raise CoverageCompletenessError("SOURCE_COVERAGE_RECEIPT_FROM_FUTURE")
    class_ids = {str(item["class_id"]) for item in receipt["coverage_classes"]}
    allocation = _normalize_allocation(allocation_percent, class_ids=class_ids)

    normalized_evidence = None
    rejection_reasons: list[str] = []
    if evidence is not None:
        normalized_evidence, rejection_reasons = _normalize_evidence(
            evidence,
            universe_hash=receipt["universe_hash"],
            evaluated_at_ms=evaluated_at_ms,
        )

    body = {
        "schema_version": COMPLETENESS_ATTESTATION_SCHEMA,
        "workflow_id": receipt["workflow_id"],
        "source_coverage_receipt_hash": receipt["receipt_hash"],
        "universe_hash": receipt["universe_hash"],
        "evaluated_at_ms": evaluated_at_ms,
        "allocation": allocation,
        "coverage_state": "COVERAGE_UNKNOWN",
        "completeness_claimed": False,
        "empirical_evidence_available": False,
        "completeness_evidence": normalized_evidence,
        "evidence_rejection_reasons": rejection_reasons,
        "paper_read_only": True,
        "real_execution": False,
        "execution_capability": "NONE",
    }
    return {**body, "attestation_hash": _hash(body)}


__all__ = [
    "COMPLETENESS_ATTESTATION_SCHEMA",
    "COMPLETENESS_EVIDENCE_KINDS",
    "CoverageCompletenessError",
    "build_coverage_completeness_attestation",
]
