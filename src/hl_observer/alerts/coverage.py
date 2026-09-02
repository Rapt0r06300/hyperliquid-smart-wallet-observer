"""Explicit, fail-closed source universe and coverage-gap receipts.

The coverage universe is a research declaration, not evidence that the declared
sources are connected or complete. Runtime observations are reconciled against
that declaration and every missing, stale or unvalidated source becomes an
explicit gap. This module is pure and local: it has no network or execution
capability.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

COVERAGE_UNIVERSE_SCHEMA = "hypersmart.source_coverage_universe.v1"
COVERAGE_RECEIPT_SCHEMA = "hypersmart.source_coverage_receipt.v1"
SOURCE_CLASSES = (
    "SEC_FILINGS",
    "OFFICIAL_MACRO_RELEASES",
    "COMPANY_IR",
    "VENUE_NOTICES",
    "MARKET_MICROSTRUCTURE",
    "SELECTED_PUBLIC_NEWS",
    "ONCHAIN_PUBLIC_CRYPTO",
)
CONNECTION_STATES = frozenset(
    {"CONNECTED", "DISCONNECTED", "INTENTIONALLY_DISABLED", "UNKNOWN"}
)
SOURCE_STATES = frozenset(
    {
        "HEALTHY",
        "DEGRADED",
        "STALE",
        "RATE_LIMITED",
        "AUTH_REQUIRED",
        "UNREACHABLE",
        "SEMANTIC_DRIFT",
        "COVERAGE_UNKNOWN",
    }
)
ENTITLEMENT_STATES = frozenset(
    {
        "PUBLIC_ZERO_EURO",
        "LOCAL_ZERO_EURO",
        "OPTIONAL_PAID",
        "USER_PROVIDED",
        "UNKNOWN",
    }
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,159}$")


class SourceCoverageError(ValueError):
    """Raised when coverage metadata could support a misleading claim."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _text(value: object, *, field: str, maximum: int = 500) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise SourceCoverageError(f"COVERAGE_TEXT_INVALID:{field}")
    return normalized


def _identifier(value: object, *, field: str) -> str:
    normalized = _text(value, field=field, maximum=160)
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise SourceCoverageError(f"COVERAGE_IDENTIFIER_INVALID:{field}")
    return normalized


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool):
        raise SourceCoverageError(f"COVERAGE_INTEGER_INVALID:{field}")
    try:
        normalized = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SourceCoverageError(f"COVERAGE_INTEGER_INVALID:{field}") from exc
    if normalized <= 0:
        raise SourceCoverageError(f"COVERAGE_INTEGER_INVALID:{field}")
    return normalized


def _optional_nonnegative_int(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise SourceCoverageError(f"COVERAGE_INTEGER_INVALID:{field}")
    try:
        normalized = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SourceCoverageError(f"COVERAGE_INTEGER_INVALID:{field}") from exc
    if normalized < 0:
        raise SourceCoverageError(f"COVERAGE_INTEGER_INVALID:{field}")
    return normalized


def _optional_nonnegative_float(value: object, *, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise SourceCoverageError(f"COVERAGE_NUMBER_INVALID:{field}")
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SourceCoverageError(f"COVERAGE_NUMBER_INVALID:{field}") from exc
    if not math.isfinite(normalized) or normalized < 0:
        raise SourceCoverageError(f"COVERAGE_NUMBER_INVALID:{field}")
    return round(normalized, 6)


def _string_list(value: object, *, field: str, maximum: int = 128) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise SourceCoverageError(f"COVERAGE_LIST_INVALID:{field}")
    normalized = [_text(item, field=field) for item in value]
    if len(set(normalized)) != len(normalized):
        raise SourceCoverageError(f"COVERAGE_LIST_DUPLICATE:{field}")
    return sorted(normalized)


def validate_source_coverage_universe(payload: object) -> dict[str, Any]:
    """Validate and normalize one workflow's intended source universe."""

    if not isinstance(payload, Mapping):
        raise SourceCoverageError("COVERAGE_UNIVERSE_NOT_MAPPING")
    if payload.get("schema_version") != COVERAGE_UNIVERSE_SCHEMA:
        raise SourceCoverageError("COVERAGE_UNIVERSE_SCHEMA_INVALID")
    if payload.get("paper_read_only") is not True:
        raise SourceCoverageError("COVERAGE_PAPER_READ_ONLY_REQUIRED")
    if payload.get("real_execution") is not False:
        raise SourceCoverageError("COVERAGE_REAL_EXECUTION_FORBIDDEN")

    workflow_id = _identifier(payload.get("workflow_id"), field="workflow_id")
    description = _text(payload.get("description"), field="description", maximum=2_000)
    raw_classes = payload.get("coverage_classes")
    if not isinstance(raw_classes, list) or not raw_classes:
        raise SourceCoverageError("COVERAGE_CLASSES_MISSING")

    classes: list[dict[str, Any]] = []
    seen_classes: set[str] = set()
    seen_sources: set[str] = set()
    for raw_class in raw_classes:
        if not isinstance(raw_class, Mapping):
            raise SourceCoverageError("COVERAGE_CLASS_NOT_MAPPING")
        class_id = _identifier(raw_class.get("class_id"), field="class_id").upper()
        if class_id not in SOURCE_CLASSES:
            raise SourceCoverageError(f"COVERAGE_CLASS_UNKNOWN:{class_id}")
        if class_id in seen_classes:
            raise SourceCoverageError(f"COVERAGE_CLASS_DUPLICATE:{class_id}")
        seen_classes.add(class_id)

        raw_sources = raw_class.get("desired_sources")
        if not isinstance(raw_sources, list) or not raw_sources:
            raise SourceCoverageError(f"DESIRED_SOURCES_MISSING:{class_id}")
        desired_sources: list[dict[str, Any]] = []
        for raw_source in raw_sources:
            if not isinstance(raw_source, Mapping):
                raise SourceCoverageError(f"DESIRED_SOURCE_NOT_MAPPING:{class_id}")
            source_id = _identifier(raw_source.get("source_id"), field="source_id")
            if source_id in seen_sources:
                raise SourceCoverageError(f"DESIRED_SOURCE_DUPLICATE:{source_id}")
            seen_sources.add(source_id)
            entitlement = _text(
                raw_source.get("entitlement"), field="entitlement"
            ).upper()
            if entitlement not in ENTITLEMENT_STATES:
                raise SourceCoverageError(f"ENTITLEMENT_INVALID:{source_id}")
            desired_sources.append(
                {
                    "source_id": source_id,
                    "authority": _text(raw_source.get("authority"), field="authority"),
                    "required": raw_source.get("required") is True,
                    "entitlement": entitlement,
                    "license_class": _text(
                        raw_source.get("license_class"), field="license_class"
                    ),
                    "latency_slo_ms": _positive_int(
                        raw_source.get("latency_slo_ms"), field="latency_slo_ms"
                    ),
                    "freshness_slo_ms": _positive_int(
                        raw_source.get("freshness_slo_ms"), field="freshness_slo_ms"
                    ),
                    "validation_slo_ms": _positive_int(
                        raw_source.get("validation_slo_ms"),
                        field="validation_slo_ms",
                    ),
                }
            )
        classes.append(
            {
                "class_id": class_id,
                "desired_sources": sorted(
                    desired_sources, key=lambda item: item["source_id"]
                ),
                "known_exclusions": _string_list(
                    raw_class.get("known_exclusions"),
                    field=f"known_exclusions:{class_id}",
                ),
            }
        )

    normalized = {
        "schema_version": COVERAGE_UNIVERSE_SCHEMA,
        "workflow_id": workflow_id,
        "description": description,
        "coverage_classes": sorted(classes, key=lambda item: item["class_id"]),
        "paper_read_only": True,
        "real_execution": False,
    }
    normalized["universe_hash"] = _hash(normalized)
    supplied_hash = payload.get("universe_hash")
    if supplied_hash is not None and supplied_hash != normalized["universe_hash"]:
        raise SourceCoverageError("COVERAGE_UNIVERSE_HASH_MISMATCH")
    return normalized


def load_source_coverage_universe(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceCoverageError("COVERAGE_UNIVERSE_FILE_INVALID") from exc
    return validate_source_coverage_universe(payload)


def _normalize_observations(
    observations: Sequence[Mapping[str, Any]],
    *,
    desired_source_ids: set[str],
) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for raw in observations:
        if not isinstance(raw, Mapping):
            raise SourceCoverageError("SOURCE_OBSERVATION_NOT_MAPPING")
        source_id = _identifier(raw.get("source_id"), field="source_id")
        if source_id not in desired_source_ids:
            raise SourceCoverageError(f"OBSERVED_SOURCE_UNDECLARED:{source_id}")
        if source_id in normalized:
            raise SourceCoverageError(f"SOURCE_OBSERVATION_DUPLICATE:{source_id}")
        connection_state = _text(
            raw.get("connection_state"), field="connection_state"
        ).upper()
        source_status = _text(raw.get("source_status"), field="source_status").upper()
        entitlement = _text(raw.get("entitlement"), field="entitlement").upper()
        if connection_state not in CONNECTION_STATES:
            raise SourceCoverageError(f"CONNECTION_STATE_INVALID:{source_id}")
        if source_status not in SOURCE_STATES:
            raise SourceCoverageError(f"SOURCE_STATUS_INVALID:{source_id}")
        if entitlement not in ENTITLEMENT_STATES:
            raise SourceCoverageError(f"ENTITLEMENT_INVALID:{source_id}")
        normalized[source_id] = {
            "source_id": source_id,
            "connection_state": connection_state,
            "source_status": source_status,
            "entitlement": entitlement,
            "license_class": _text(
                raw.get("license_class"), field="license_class"
            ),
            "latency_ms": _optional_nonnegative_float(
                raw.get("latency_ms"), field="latency_ms"
            ),
            "last_successful_refresh_ms": _optional_nonnegative_int(
                raw.get("last_successful_refresh_ms"),
                field="last_successful_refresh_ms",
            ),
            "last_validated_at_ms": _optional_nonnegative_int(
                raw.get("last_validated_at_ms"), field="last_validated_at_ms"
            ),
            "validation_evidence_refs": _string_list(
                raw.get("validation_evidence_refs", []),
                field=f"validation_evidence_refs:{source_id}",
            ),
        }
    return normalized


def _gap(
    *,
    workflow_id: str,
    class_id: str,
    source_id: str | None,
    code: str,
    severity: str,
    detail: str,
) -> dict[str, str | None]:
    body = {
        "workflow_id": workflow_id,
        "class_id": class_id,
        "source_id": source_id,
        "code": code,
        "severity": severity,
        "detail": detail,
    }
    return {"gap_id": _hash(body), **body}


def _append_gap(
    gaps: list[dict[str, str | None]],
    *,
    workflow_id: str,
    class_id: str,
    source_id: str,
    code: str,
    severity: str,
    detail: str,
) -> None:
    gaps.append(
        _gap(
            workflow_id=workflow_id,
            class_id=class_id,
            source_id=source_id,
            code=code,
            severity=severity,
            detail=detail,
        )
    )


def build_source_coverage_receipt(
    universe: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    *,
    evaluated_at_ms: int,
) -> dict[str, Any]:
    """Reconcile runtime observations with the declared universe.

    Operational readiness only means that the explicitly desired source set is
    currently usable. It never upgrades empirical completeness, which remains
    ``COVERAGE_UNKNOWN`` until a separate measured-recall receipt exists.
    """

    evaluated_at_ms = _optional_nonnegative_int(
        evaluated_at_ms, field="evaluated_at_ms"
    )
    if evaluated_at_ms is None:
        raise SourceCoverageError("COVERAGE_INTEGER_INVALID:evaluated_at_ms")
    declared = validate_source_coverage_universe(universe)
    desired_source_ids = {
        source["source_id"]
        for item in declared["coverage_classes"]
        for source in item["desired_sources"]
    }
    observed = _normalize_observations(
        observations, desired_source_ids=desired_source_ids
    )

    workflow_id = declared["workflow_id"]
    gaps: list[dict[str, str | None]] = []
    class_receipts: list[dict[str, Any]] = []
    for class_definition in declared["coverage_classes"]:
        class_id = class_definition["class_id"]
        source_receipts: list[dict[str, Any]] = []
        class_gaps: list[dict[str, str | None]] = []
        for desired in class_definition["desired_sources"]:
            source_id = desired["source_id"]
            actual = observed.get(source_id)
            if actual is None:
                actual = {
                    "source_id": source_id,
                    "connection_state": "UNKNOWN",
                    "source_status": "COVERAGE_UNKNOWN",
                    "entitlement": "UNKNOWN",
                    "license_class": "UNKNOWN",
                    "latency_ms": None,
                    "last_successful_refresh_ms": None,
                    "last_validated_at_ms": None,
                    "validation_evidence_refs": [],
                }

            severity = "BLOCKING" if desired["required"] else "WARNING"

            if actual["connection_state"] != "CONNECTED":
                _append_gap(
                    class_gaps,
                    workflow_id=workflow_id,
                    class_id=class_id,
                    source_id=source_id,
                    code="SOURCE_NOT_CONNECTED",
                    severity=severity,
                    detail=actual["connection_state"],
                )
            if actual["source_status"] != "HEALTHY":
                _append_gap(
                    class_gaps,
                    workflow_id=workflow_id,
                    class_id=class_id,
                    source_id=source_id,
                    code="SOURCE_NOT_HEALTHY",
                    severity=severity,
                    detail=actual["source_status"],
                )
            if actual["entitlement"] != desired["entitlement"]:
                _append_gap(
                    class_gaps,
                    workflow_id=workflow_id,
                    class_id=class_id,
                    source_id=source_id,
                    code="ENTITLEMENT_MISMATCH",
                    severity=severity,
                    detail=(
                        f"expected={desired['entitlement']};"
                        f"actual={actual['entitlement']}"
                    ),
                )
            if actual["license_class"] != desired["license_class"]:
                _append_gap(
                    class_gaps,
                    workflow_id=workflow_id,
                    class_id=class_id,
                    source_id=source_id,
                    code="LICENSE_MISMATCH",
                    severity=severity,
                    detail=(
                        f"expected={desired['license_class']};"
                        f"actual={actual['license_class']}"
                    ),
                )

            latency_ms = actual["latency_ms"]
            if latency_ms is None:
                _append_gap(
                    class_gaps,
                    workflow_id=workflow_id,
                    class_id=class_id,
                    source_id=source_id,
                    code="LATENCY_UNMEASURED",
                    severity=severity,
                    detail="No measured latency",
                )
            elif latency_ms > desired["latency_slo_ms"]:
                _append_gap(
                    class_gaps,
                    workflow_id=workflow_id,
                    class_id=class_id,
                    source_id=source_id,
                    code="LATENCY_SLO_BREACH",
                    severity=severity,
                    detail=(
                        f"latency_ms={latency_ms};"
                        f"slo_ms={desired['latency_slo_ms']}"
                    ),
                )

            refresh_ms = actual["last_successful_refresh_ms"]
            refresh_age_ms = None if refresh_ms is None else evaluated_at_ms - refresh_ms
            if refresh_age_ms is None:
                _append_gap(
                    class_gaps,
                    workflow_id=workflow_id,
                    class_id=class_id,
                    source_id=source_id,
                    code="FRESHNESS_UNMEASURED",
                    severity=severity,
                    detail="No successful refresh timestamp",
                )
            elif refresh_age_ms < 0:
                _append_gap(
                    class_gaps,
                    workflow_id=workflow_id,
                    class_id=class_id,
                    source_id=source_id,
                    code="REFRESH_TIMESTAMP_IN_FUTURE",
                    severity=severity,
                    detail=f"age_ms={refresh_age_ms}",
                )
            elif refresh_age_ms > desired["freshness_slo_ms"]:
                _append_gap(
                    class_gaps,
                    workflow_id=workflow_id,
                    class_id=class_id,
                    source_id=source_id,
                    code="FRESHNESS_SLO_BREACH",
                    severity=severity,
                    detail=(
                        f"age_ms={refresh_age_ms};"
                        f"slo_ms={desired['freshness_slo_ms']}"
                    ),
                )

            validated_ms = actual["last_validated_at_ms"]
            validation_age_ms = (
                None if validated_ms is None else evaluated_at_ms - validated_ms
            )
            if validation_age_ms is None:
                _append_gap(
                    class_gaps,
                    workflow_id=workflow_id,
                    class_id=class_id,
                    source_id=source_id,
                    code="LAST_VALIDATION_MISSING",
                    severity=severity,
                    detail="No validation timestamp",
                )
            elif validation_age_ms < 0:
                _append_gap(
                    class_gaps,
                    workflow_id=workflow_id,
                    class_id=class_id,
                    source_id=source_id,
                    code="VALIDATION_TIMESTAMP_IN_FUTURE",
                    severity=severity,
                    detail=f"age_ms={validation_age_ms}",
                )
            elif validation_age_ms > desired["validation_slo_ms"]:
                _append_gap(
                    class_gaps,
                    workflow_id=workflow_id,
                    class_id=class_id,
                    source_id=source_id,
                    code="VALIDATION_STALE",
                    severity=severity,
                    detail=(
                        f"age_ms={validation_age_ms};"
                        f"slo_ms={desired['validation_slo_ms']}"
                    ),
                )
            if not actual["validation_evidence_refs"]:
                _append_gap(
                    class_gaps,
                    workflow_id=workflow_id,
                    class_id=class_id,
                    source_id=source_id,
                    code="VALIDATION_EVIDENCE_MISSING",
                    severity=severity,
                    detail="No empirical validation reference",
                )

            source_receipts.append(
                {
                    "source_id": source_id,
                    "authority": desired["authority"],
                    "required": desired["required"],
                    "connection_state": actual["connection_state"],
                    "source_status": actual["source_status"],
                    "entitlement": actual["entitlement"],
                    "license_class": actual["license_class"],
                    "latency_ms": latency_ms,
                    "latency_slo_ms": desired["latency_slo_ms"],
                    "last_successful_refresh_ms": refresh_ms,
                    "refresh_age_ms": refresh_age_ms,
                    "freshness_slo_ms": desired["freshness_slo_ms"],
                    "last_validated_at_ms": validated_ms,
                    "validation_age_ms": validation_age_ms,
                    "validation_slo_ms": desired["validation_slo_ms"],
                    "validation_evidence_refs": actual["validation_evidence_refs"],
                }
            )

        for exclusion in class_definition["known_exclusions"]:
            class_gaps.append(
                _gap(
                    workflow_id=workflow_id,
                    class_id=class_id,
                    source_id=None,
                    code="KNOWN_EXCLUSION",
                    severity="DISCLOSED",
                    detail=exclusion,
                )
            )
        gaps.extend(class_gaps)
        blocking_count = sum(gap["severity"] == "BLOCKING" for gap in class_gaps)
        connected = sorted(
            source["source_id"]
            for source in source_receipts
            if source["connection_state"] == "CONNECTED"
        )
        class_receipts.append(
            {
                "class_id": class_id,
                "desired_sources": [
                    source["source_id"] for source in source_receipts
                ],
                "actually_connected_sources": connected,
                "source_status": source_receipts,
                "known_exclusions": class_definition["known_exclusions"],
                "operational_state": "READY" if blocking_count == 0 else "BLOCKED",
                "completeness_state": "COVERAGE_UNKNOWN",
                "gap_count": len(class_gaps),
                "blocking_gap_count": blocking_count,
            }
        )

    ordered_gaps = sorted(gaps, key=lambda item: str(item["gap_id"]))
    blocking_gaps = sum(gap["severity"] == "BLOCKING" for gap in ordered_gaps)
    body = {
        "schema_version": COVERAGE_RECEIPT_SCHEMA,
        "workflow_id": workflow_id,
        "universe_hash": declared["universe_hash"],
        "evaluated_at_ms": evaluated_at_ms,
        "coverage_classes": class_receipts,
        "gap_ledger": ordered_gaps,
        "counts": {
            "classes": len(class_receipts),
            "desired_sources": len(desired_source_ids),
            "actually_connected_sources": sum(
                len(item["actually_connected_sources"]) for item in class_receipts
            ),
            "gaps": len(ordered_gaps),
            "blocking_gaps": blocking_gaps,
        },
        "operational_state": "READY" if blocking_gaps == 0 else "BLOCKED",
        "completeness_state": "COVERAGE_UNKNOWN",
        "completeness_claimed": False,
        "allocation_is_not_completeness_evidence": True,
        "paper_read_only": True,
        "real_execution": False,
        "execution_capability": "NONE",
    }
    return {**body, "receipt_hash": _hash(body)}


__all__ = [
    "CONNECTION_STATES",
    "COVERAGE_RECEIPT_SCHEMA",
    "COVERAGE_UNIVERSE_SCHEMA",
    "ENTITLEMENT_STATES",
    "SOURCE_CLASSES",
    "SOURCE_STATES",
    "SourceCoverageError",
    "build_source_coverage_receipt",
    "load_source_coverage_universe",
    "validate_source_coverage_universe",
]
