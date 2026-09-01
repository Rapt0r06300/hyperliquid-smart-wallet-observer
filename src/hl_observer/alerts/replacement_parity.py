"""Fail-closed capability decomposition for replacement/parity claims."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

PARITY_SCHEMA = "hypersmart.replacement_parity.v1"
PARITY_DIMENSIONS = (
    "source_data_rights",
    "asset_coverage",
    "event_news_coverage",
    "historical_depth",
    "real_time_latency",
    "timestamp_quality",
    "provenance",
    "corrections_retractions",
    "analytics",
    "communications_network",
    "execution_capabilities",
    "reliability_sla",
    "compliance_audit",
    "entitlements_permissions",
    "export_api_capabilities",
    "cost_tco",
    "privacy_security",
    "offline_local_path",
)
DIMENSION_STATES = frozenset(
    {"PROVEN", "PARTIAL", "ABSENT", "UNKNOWN", "NOT_APPLICABLE"}
)
PARITY_VERDICTS = frozenset(
    {
        "PARITY_PROVEN",
        "PARTIAL_SUBSTITUTE",
        "COMPLEMENT",
        "DISCOVERY_ONLY",
        "NO_PARITY_EVIDENCE",
        "REJECTED",
    }
)


class ReplacementParityError(ValueError):
    """Raised when a replacement claim lacks a complete honest decomposition."""


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_replacement_assessment(payload: object) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ReplacementParityError("ASSESSMENT_NOT_MAPPING")
    assessment = dict(payload)
    if assessment.get("schema_version") != PARITY_SCHEMA:
        raise ReplacementParityError("ASSESSMENT_SCHEMA_INVALID")
    subject = str(assessment.get("subject") or "").strip()
    reference = str(assessment.get("reference") or "").strip()
    scope = str(assessment.get("scope") or "").strip()
    verdict = str(assessment.get("verdict") or "").strip().upper()
    if not subject or not reference or not scope:
        raise ReplacementParityError("ASSESSMENT_IDENTITY_MISSING")
    if verdict not in PARITY_VERDICTS:
        raise ReplacementParityError("ASSESSMENT_VERDICT_INVALID")
    dimensions = assessment.get("dimensions")
    if not isinstance(dimensions, Mapping):
        raise ReplacementParityError("ASSESSMENT_DIMENSIONS_MISSING")
    keys = set(str(key) for key in dimensions)
    expected = set(PARITY_DIMENSIONS)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise ReplacementParityError(
            f"ASSESSMENT_DIMENSIONS_INCOMPLETE:missing={missing}:extra={extra}"
        )

    normalized_dimensions: dict[str, dict[str, Any]] = {}
    for dimension in PARITY_DIMENSIONS:
        raw = dimensions[dimension]
        if not isinstance(raw, Mapping):
            raise ReplacementParityError(f"DIMENSION_NOT_MAPPING:{dimension}")
        state = str(raw.get("state") or "").strip().upper()
        rationale = str(raw.get("rationale") or "").strip()
        refs_raw = raw.get("evidence_refs", [])
        if state not in DIMENSION_STATES or not rationale:
            raise ReplacementParityError(f"DIMENSION_INVALID:{dimension}")
        if not isinstance(refs_raw, list) or any(
            not str(ref).strip() for ref in refs_raw
        ):
            raise ReplacementParityError(f"DIMENSION_EVIDENCE_INVALID:{dimension}")
        evidence_refs = sorted(set(str(ref).strip() for ref in refs_raw))
        if state in {"PROVEN", "PARTIAL"} and not evidence_refs:
            raise ReplacementParityError(f"DIMENSION_EVIDENCE_MISSING:{dimension}")
        normalized_dimensions[dimension] = {
            "state": state,
            "rationale": rationale,
            "evidence_refs": evidence_refs,
        }

    states = [item["state"] for item in normalized_dimensions.values()]
    supported = sum(state in {"PROVEN", "PARTIAL"} for state in states)
    gaps = sum(state in {"PARTIAL", "ABSENT", "UNKNOWN"} for state in states)
    if verdict == "PARITY_PROVEN" and any(
        state not in {"PROVEN", "NOT_APPLICABLE"} for state in states
    ):
        raise ReplacementParityError("PARITY_PROVEN_WITH_CAPABILITY_GAPS")
    if verdict == "PARTIAL_SUBSTITUTE" and (supported == 0 or gaps == 0):
        raise ReplacementParityError("PARTIAL_SUBSTITUTE_MATRIX_INCOHERENT")
    if verdict == "NO_PARITY_EVIDENCE" and supported:
        raise ReplacementParityError("NO_PARITY_EVIDENCE_WITH_SUPPORTED_DIMENSION")

    normalized = {
        "schema_version": PARITY_SCHEMA,
        "subject": subject,
        "reference": reference,
        "scope": scope,
        "verdict": verdict,
        "dimensions": normalized_dimensions,
        "paper_read_only": True,
        "real_execution": False,
    }
    if assessment.get("paper_read_only") is not True:
        raise ReplacementParityError("PAPER_READ_ONLY_REQUIRED")
    if assessment.get("real_execution") is not False:
        raise ReplacementParityError("REAL_EXECUTION_FORBIDDEN")
    normalized["assessment_hash"] = _canonical_hash(normalized)
    supplied_hash = assessment.get("assessment_hash")
    if supplied_hash is not None and supplied_hash != normalized["assessment_hash"]:
        raise ReplacementParityError("ASSESSMENT_HASH_MISMATCH")
    return normalized


def load_replacement_assessment(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReplacementParityError("ASSESSMENT_FILE_INVALID") from exc
    return validate_replacement_assessment(payload)


__all__ = [
    "DIMENSION_STATES",
    "PARITY_DIMENSIONS",
    "PARITY_SCHEMA",
    "PARITY_VERDICTS",
    "ReplacementParityError",
    "load_replacement_assessment",
    "validate_replacement_assessment",
]
