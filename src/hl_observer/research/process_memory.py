"""Append-only offline process memory for Codex Discovery V3.2.

The records stored here are research guidance only. They never certify economic
performance and this module performs no network or exchange I/O.
"""
from __future__ import annotations

import json
import math
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hl_observer.research.hypothesis_ledger import FAMILIES

SCHEMA_VERSION = 1
OUTCOMES = frozenset({"SUCCESS", "FAILURE", "NEUTRAL", "BLOCKED"})
PROVENANCE = frozenset({"runtime", "historical"})
_HIGH_CONFIDENCE = 0.90
_HIGH_EVIDENCE = 5
_POSITIVE_BOOST_CAP = 0.25


class ProcessMemoryValidationError(ValueError):
    """Raised when a V3.2 process-memory record is malformed."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _text(value: Any, name: str, *, optional: bool = False, max_len: int = 2000) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ProcessMemoryValidationError(f"{name} must be a non-empty string")
    normalized = " ".join(value.split())
    if len(normalized) > max_len:
        raise ProcessMemoryValidationError(f"{name} exceeds {max_len} characters")
    return normalized


def _strings(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        raw = list(value)
    else:
        raise ProcessMemoryValidationError(f"{name} must be a string or list of strings")
    output: list[str] = []
    seen: set[str] = set()
    for item in raw:
        normalized = _text(item, name, max_len=500)
        assert normalized is not None
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            output.append(normalized)
    output.sort(key=str.casefold)
    return output


def _timestamp(value: Any) -> str:
    text = _text(value or _utc_now(), "created_at_utc", max_len=64)
    assert text is not None
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ProcessMemoryValidationError("created_at_utc must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ProcessMemoryValidationError("created_at_utc must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def validate_process_record(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one process-memory record."""
    if not isinstance(payload, Mapping):
        raise ProcessMemoryValidationError("record must be a JSON object")
    if payload.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise ProcessMemoryValidationError(f"schema_version must be {SCHEMA_VERSION}")

    family = payload.get("family")
    if family not in FAMILIES:
        raise ProcessMemoryValidationError(f"family must be one of {sorted(FAMILIES)}")
    outcome = payload.get("outcome")
    if outcome not in OUTCOMES:
        raise ProcessMemoryValidationError(f"outcome must be one of {sorted(OUTCOMES)}")
    provenance = payload.get("provenance")
    if provenance not in PROVENANCE:
        raise ProcessMemoryValidationError(
            f"provenance must be one of {sorted(PROVENANCE)}"
        )

    evidence_count = payload.get("evidence_count", 0)
    if (
        not isinstance(evidence_count, int)
        or isinstance(evidence_count, bool)
        or evidence_count < 0
    ):
        raise ProcessMemoryValidationError("evidence_count must be a non-negative integer")
    confidence = payload.get("confidence", 0.0)
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not math.isfinite(float(confidence))
        or not 0.0 <= float(confidence) <= 1.0
    ):
        raise ProcessMemoryValidationError("confidence must be finite and between 0 and 1")
    certifying = payload.get("certifying", False)
    if not isinstance(certifying, bool):
        raise ProcessMemoryValidationError("certifying must be boolean")
    if certifying:
        raise ProcessMemoryValidationError("process memory is guidance only and cannot certify")

    record_id = _text(payload.get("record_id") or f"PM-{uuid.uuid4().hex}", "record_id", max_len=160)
    mechanism = _text(payload.get("mechanism_signature"), "mechanism_signature", max_len=1000)
    change_motif = _text(payload.get("change_motif"), "change_motif", max_len=1000)
    assert record_id is not None and mechanism is not None and change_motif is not None

    return {
        "schema_version": SCHEMA_VERSION,
        "record_id": record_id,
        "created_at_utc": _timestamp(payload.get("created_at_utc")),
        "family": family,
        "mechanism_signature": mechanism,
        "context": _strings(payload.get("context", []), "context"),
        "change_motif": change_motif,
        "outcome": outcome,
        "evidence_count": evidence_count,
        "confidence": round(float(confidence), 6),
        "failure_reason": _text(payload.get("failure_reason"), "failure_reason", optional=True),
        "success_evidence": _text(
            payload.get("success_evidence"), "success_evidence", optional=True
        ),
        "provenance": provenance,
        "certifying": False,
        "retest_condition": _text(
            payload.get("retest_condition"), "retest_condition", optional=True
        ),
    }


def load_process_records(path: str | Path, family: str | None = None) -> list[dict[str, Any]]:
    """Load validated JSONL process memory, optionally filtering by canonical family."""
    if family is not None and family not in FAMILIES:
        raise ProcessMemoryValidationError(f"family must be one of {sorted(FAMILIES)}")
    target = Path(path)
    if not target.exists():
        return []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProcessMemoryValidationError(
                f"invalid JSON at process-memory line {line_number}"
            ) from exc
        record = validate_process_record(payload)
        if record["record_id"] in seen:
            raise ProcessMemoryValidationError(
                f"duplicate record_id {record['record_id']} at line {line_number}"
            )
        seen.add(record["record_id"])
        if family is None or record["family"] == family:
            records.append(record)
    return records


def append_process_record(path: str | Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and append one record without rewriting prior history."""
    record = validate_process_record(payload)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = {item["record_id"] for item in load_process_records(target)}
    if record["record_id"] in existing:
        raise ProcessMemoryValidationError(f"record_id already exists: {record['record_id']}")
    encoded = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded + "\n")
        handle.flush()
    return record


def _normalized_candidate(candidate: Mapping[str, Any]) -> tuple[str, str, set[str], set[str]]:
    family = candidate.get("family")
    if family not in FAMILIES:
        raise ProcessMemoryValidationError(f"family must be one of {sorted(FAMILIES)}")
    mechanism = _text(candidate.get("mechanism_signature"), "mechanism_signature")
    assert mechanism is not None
    context = {item.casefold() for item in _strings(candidate.get("context", []), "context")}
    retest = {
        item.casefold() for item in _strings(candidate.get("retest_evidence", []), "retest_evidence")
    }
    return family, mechanism.casefold(), context, retest


def _context_matches(candidate: set[str], historical: set[str]) -> bool:
    if not candidate or not historical:
        return True
    intersection = len(candidate & historical)
    union = len(candidate | historical)
    return union > 0 and (intersection / union) >= 0.5


def _retest_satisfied(condition: str | None, evidence: set[str]) -> bool:
    if not condition or not evidence:
        return False
    needle = condition.casefold()
    return any(needle in item or item in needle for item in evidence)


def candidate_memory_effect(
    candidate: Mapping[str, Any], records: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Return asymmetric negative-veto and bounded positive-prior effects."""
    family, mechanism, context, retest_evidence = _normalized_candidate(candidate)
    matching: list[dict[str, Any]] = []
    for raw in records:
        record = validate_process_record(raw)
        record_context = {item.casefold() for item in record["context"]}
        if record["family"] != family:
            continue
        if record["mechanism_signature"].casefold() != mechanism:
            continue
        if not _context_matches(context, record_context):
            continue
        matching.append(record)

    failures = [
        item
        for item in matching
        if item["outcome"] in {"FAILURE", "BLOCKED"}
        and item["confidence"] >= _HIGH_CONFIDENCE
        and item["evidence_count"] >= _HIGH_EVIDENCE
    ]
    retest_override = any(
        _retest_satisfied(item["retest_condition"], retest_evidence) for item in failures
    )
    veto = len(failures) >= 2 and not retest_override

    positive = [
        item
        for item in matching
        if item["outcome"] == "SUCCESS"
        and item["confidence"] >= 0.60
        and item["evidence_count"] > 0
    ]
    boost = sum(
        min(0.10, 0.10 * item["confidence"] * min(1.0, item["evidence_count"] / 10.0))
        for item in positive
    )
    boost = round(min(_POSITIVE_BOOST_CAP, boost), 6)
    return {
        "veto": veto,
        "boost": boost,
        "matching_records": len(matching),
        "high_confidence_failures": len(failures),
        "positive_records": len(positive),
        "retest_override": retest_override,
        "failure_reasons": sorted(
            {item["failure_reason"] for item in failures if item["failure_reason"]}
        ),
    }


def process_memory_summary(
    records: Iterable[Mapping[str, Any]], family: str | None = None
) -> dict[str, Any]:
    """Return a compact summary suitable for the V3.2 resume pack."""
    if family is not None and family not in FAMILIES:
        raise ProcessMemoryValidationError(f"family must be one of {sorted(FAMILIES)}")
    normalized = [validate_process_record(item) for item in records]
    if family is not None:
        normalized = [item for item in normalized if item["family"] == family]
    normalized.sort(key=lambda item: (item["created_at_utc"], item["record_id"]))

    high_failures = Counter(
        item["mechanism_signature"]
        for item in normalized
        if item["outcome"] in {"FAILURE", "BLOCKED"}
        and item["confidence"] >= _HIGH_CONFIDENCE
        and item["evidence_count"] >= _HIGH_EVIDENCE
    )
    veto_motifs = sorted(motif for motif, count in high_failures.items() if count >= 2)
    outcome_counts = Counter(item["outcome"] for item in normalized)
    useful = [
        {
            "record_id": item["record_id"],
            "mechanism_signature": item["mechanism_signature"],
            "outcome": item["outcome"],
            "confidence": item["confidence"],
        }
        for item in normalized
        if item["outcome"] == "SUCCESS" or item["confidence"] >= _HIGH_CONFIDENCE
    ][-5:]
    return {
        "schema_version": SCHEMA_VERSION,
        "family": family,
        "records": len(normalized),
        "outcomes": {key: outcome_counts.get(key, 0) for key in sorted(OUTCOMES)},
        "high_confidence_veto_motifs": veto_motifs,
        "recent_useful": useful,
    }


__all__ = [
    "OUTCOMES",
    "PROVENANCE",
    "ProcessMemoryValidationError",
    "SCHEMA_VERSION",
    "append_process_record",
    "candidate_memory_effect",
    "load_process_records",
    "process_memory_summary",
    "validate_process_record",
]
