"""Fail-closed evidence gate for Copy-Vault task closure.

The gate is deliberately narrower than an Agiflow task list: callers provide the
criteria read from Agiflow and the evidence records they actually received.  It
does not contact GitHub, download data, mutate task status, or infer missing
economic evidence.  Its only job is to make an exact-SHA proof matrix
deterministic and impossible to close accidentally with queued, partial,
unsafe, or synthetic evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA = "hypersmart.copy_vault_closure_evidence_matrix.v1"
PROVEN = "PROVEN"
NOT_PROVEN = "NOT_PROVEN"
UNMEASURABLE = "UNMEASURABLE"
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_SAFE_RUN_STATUSES = frozenset({"completed"})
_SAFE_CONCLUSIONS = frozenset({"success"})
_SAFE_EVIDENCE_STATUSES = frozenset({"VERIFIED", "PASS", "COMPLETED"})
_UNSAFE_EVIDENCE_STATUSES = frozenset({
    "QUEUED", "IN_PROGRESS", "CANCELLED", "CANCELED", "PARTIAL", "UNVERIFIED",
    "FAILED", "FAILURE", "NOT_RUN", "MORE_DATA", "UNMEASURABLE",
})


def _is_full_sha(value: object) -> bool:
    return isinstance(value, str) and bool(_FULL_SHA_RE.fullmatch(value.lower()))


def _equal(actual: object, expected: object) -> bool:
    """Compare claims without allowing ``True == 1`` to pass accidentally."""

    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    return actual == expected


def _claim_at_path(claims: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    if path in claims:
        return True, claims[path]
    current: Any = claims
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _claim_matches(actual: object, expected: object) -> bool:
    if isinstance(expected, Mapping):
        if "equals" in expected and not _equal(actual, expected["equals"]):
            return False
        if expected.get("present") is True and actual is None:
            return False
        if "min" in expected:
            try:
                if isinstance(actual, bool) or actual < expected["min"]:
                    return False
            except (TypeError, ValueError):
                return False
        if "max" in expected:
            try:
                if isinstance(actual, bool) or actual > expected["max"]:
                    return False
            except (TypeError, ValueError):
                return False
        return True
    return _equal(actual, expected)


@dataclass(frozen=True)
class EvidenceRecord:
    """One externally supplied proof reference.

    ``claims`` contains only claims present in the supplied receipt; the gate
    never fills defaults.  A hosted record must include a completed successful
    run and an artifact identifier when a criterion asks for hosted evidence.
    """

    kind: str
    source: str
    head_sha: str
    evidence_status: str
    paper_read_only: bool | None
    real_execution: bool | None
    run_id: str | None = None
    artifact_id: str | None = None
    run_status: str | None = None
    conclusion: str | None = None
    artifact_sha256: str | None = None
    full_dataset_certified: bool | None = None
    claims: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvidenceRecord":
        if not isinstance(value, Mapping):
            raise ValueError("evidence record must be an object")
        claims = value.get("claims", {})
        if not isinstance(claims, Mapping):
            raise ValueError("evidence record claims must be an object")
        return cls(
            kind=str(value.get("kind") or ""),
            source=str(value.get("source") or ""),
            head_sha=str(value.get("head_sha") or "").lower(),
            evidence_status=str(value.get("evidence_status") or "").upper(),
            paper_read_only=(
                value["paper_read_only"]
                if isinstance(value.get("paper_read_only"), bool) else None
            ),
            real_execution=(
                value["real_execution"]
                if isinstance(value.get("real_execution"), bool) else None
            ),
            run_id=(str(value["run_id"]) if value.get("run_id") is not None else None),
            artifact_id=(
                str(value["artifact_id"])
                if value.get("artifact_id") is not None else None
            ),
            run_status=(
                str(value["run_status"]).lower()
                if value.get("run_status") is not None else None
            ),
            conclusion=(
                str(value["conclusion"]).lower()
                if value.get("conclusion") is not None else None
            ),
            artifact_sha256=(
                str(value["artifact_sha256"]).lower()
                if value.get("artifact_sha256") is not None else None
            ),
            full_dataset_certified=(
                value["full_dataset_certified"]
                if isinstance(value.get("full_dataset_certified"), bool) else None
            ),
            claims=dict(claims),
        )


@dataclass(frozen=True)
class ClosureCriterion:
    """A criterion copied from the authoritative Agiflow task definition."""

    criterion_id: str
    required_kinds: tuple[str, ...]
    required_claims: Mapping[str, Any] = field(default_factory=dict)
    require_hosted: bool = False
    require_full_dataset: bool = False
    min_distinct_runs: int = 1
    unavailable_is_unmeasurable: bool = False


def _criterion_errors(
    record: EvidenceRecord,
    *,
    criterion: ClosureCriterion,
    expected_head_sha: str,
) -> list[str]:
    errors: list[str] = []
    if not record.source:
        errors.append("SOURCE_MISSING")
    if record.head_sha != expected_head_sha:
        errors.append("EXACT_SHA_MISMATCH")
    if record.evidence_status in _UNSAFE_EVIDENCE_STATUSES:
        errors.append(f"EVIDENCE_STATUS_UNUSABLE:{record.evidence_status}")
    elif record.evidence_status not in _SAFE_EVIDENCE_STATUSES:
        errors.append("EVIDENCE_STATUS_MISSING_OR_UNSUPPORTED")
    if record.paper_read_only is not True:
        errors.append("PAPER_READ_ONLY_REQUIRED")
    if record.real_execution is not False:
        errors.append("REAL_EXECUTION_MUST_BE_FALSE")
    if criterion.require_hosted:
        if record.run_id is None:
            errors.append("HOSTED_RUN_ID_MISSING")
        if record.artifact_id is None:
            errors.append("HOSTED_ARTIFACT_ID_MISSING")
        if record.artifact_sha256 is None:
            errors.append("HOSTED_ARTIFACT_DIGEST_MISSING")
        if record.run_status not in _SAFE_RUN_STATUSES:
            errors.append("HOSTED_RUN_NOT_COMPLETED")
        if record.conclusion not in _SAFE_CONCLUSIONS:
            errors.append("HOSTED_RUN_NOT_SUCCESSFUL")
    if criterion.require_full_dataset and record.full_dataset_certified is not True:
        errors.append("FULL_DATASET_CERTIFICATION_MISSING")
    if record.artifact_sha256 is not None and not _is_full_sha(record.artifact_sha256):
        errors.append("ARTIFACT_SHA_INVALID")
    for path, expected in criterion.required_claims.items():
        present, actual = _claim_at_path(record.claims, path)
        if not present:
            errors.append(f"CLAIM_MISSING:{path}")
        elif not _claim_matches(actual, expected):
            errors.append(f"CLAIM_MISMATCH:{path}")
    return errors


def _validate_criterion(criterion: ClosureCriterion) -> None:
    if not criterion.criterion_id.strip():
        raise ValueError("criterion_id must be non-empty")
    if not criterion.required_kinds or any(not kind.strip() for kind in criterion.required_kinds):
        raise ValueError(f"{criterion.criterion_id}: required_kinds must be non-empty")
    if criterion.min_distinct_runs < 1:
        raise ValueError(f"{criterion.criterion_id}: min_distinct_runs must be positive")
    if criterion.require_hosted and criterion.min_distinct_runs > 1:
        # This is valid, but making it explicit prevents a caller from thinking
        # that one artifact can certify multiple hosted reruns.
        return


def evaluate_criterion(
    criterion: ClosureCriterion,
    evidence: Sequence[EvidenceRecord],
    *,
    expected_head_sha: str,
) -> dict[str, Any]:
    """Evaluate one criterion without changing any external task state."""

    _validate_criterion(criterion)
    usable: list[EvidenceRecord] = []
    reasons: list[str] = []
    for kind in criterion.required_kinds:
        kind_records = [record for record in evidence if record.kind == kind]
        if not kind_records:
            reasons.append(f"EVIDENCE_KIND_MISSING:{kind}")
            continue
        valid_for_kind = False
        for record in kind_records:
            errors = _criterion_errors(
                record, criterion=criterion, expected_head_sha=expected_head_sha,
            )
            if not errors:
                usable.append(record)
                valid_for_kind = True
            else:
                reasons.extend(f"{kind}:{reason}" for reason in errors)
        if not valid_for_kind:
            reasons.append(f"EVIDENCE_KIND_NOT_PROVEN:{kind}")

    distinct_runs = {record.run_id for record in usable if record.run_id is not None}
    distinct_artifacts = {
        record.artifact_id for record in usable if record.artifact_id is not None
    }
    if len(distinct_runs) < criterion.min_distinct_runs:
        reasons.append(
            f"DISTINCT_RUNS_INSUFFICIENT:{len(distinct_runs)}<{criterion.min_distinct_runs}"
        )
    if criterion.require_hosted and len(distinct_artifacts) < criterion.min_distinct_runs:
        reasons.append(
            "DISTINCT_ARTIFACTS_INSUFFICIENT:"
            f"{len(distinct_artifacts)}<{criterion.min_distinct_runs}"
        )
    deduped_reasons = list(dict.fromkeys(reasons))
    proven = not deduped_reasons and bool(usable)
    status = PROVEN if proven else (
        UNMEASURABLE if criterion.unavailable_is_unmeasurable else NOT_PROVEN
    )
    return {
        "criterion_id": criterion.criterion_id,
        "status": status,
        "evidence_count": len(usable),
        "run_ids": sorted(distinct_runs),
        "artifact_ids": sorted(distinct_artifacts),
        "missing_evidence": deduped_reasons,
    }


def build_closure_matrix(
    task_id: str,
    criteria: Sequence[ClosureCriterion],
    evidence: Sequence[EvidenceRecord | Mapping[str, Any]],
    *,
    expected_head_sha: str,
) -> dict[str, Any]:
    """Build an exact-SHA criterion matrix and a conservative recommendation.

    ``recommended_agiflow_state`` is informational only.  The caller must
    still re-read Agiflow and update it separately; this function has no API or
    write capability for status changes.
    """

    if not task_id.strip():
        raise ValueError("task_id must be non-empty")
    expected_head_sha = expected_head_sha.lower()
    if not _is_full_sha(expected_head_sha):
        raise ValueError("expected_head_sha must be a full hexadecimal commit SHA")
    normalized_evidence = tuple(
        item if isinstance(item, EvidenceRecord) else EvidenceRecord.from_mapping(item)
        for item in evidence
    )
    criterion_ids: set[str] = set()
    rows: list[dict[str, Any]] = []
    for criterion in criteria:
        _validate_criterion(criterion)
        if criterion.criterion_id in criterion_ids:
            raise ValueError(f"duplicate criterion_id: {criterion.criterion_id}")
        criterion_ids.add(criterion.criterion_id)
        rows.append(
            evaluate_criterion(
                criterion, normalized_evidence, expected_head_sha=expected_head_sha,
            )
        )
    if not rows:
        raise ValueError("at least one criterion is required")
    complete = all(row["status"] == PROVEN for row in rows)
    overall_status = PROVEN if complete else (
        UNMEASURABLE if any(row["status"] == UNMEASURABLE for row in rows) else NOT_PROVEN
    )
    missing = [
        f"{row['criterion_id']}:{reason}"
        for row in rows
        for reason in row["missing_evidence"]
    ]
    return {
        "schema": SCHEMA,
        "task_id": task_id,
        "expected_head_sha": expected_head_sha,
        "status": overall_status,
        "recommended_agiflow_state": "Done" if complete else "Testing",
        "closure_allowed": complete,
        "paper_read_only": True,
        "real_execution": False,
        "criteria": rows,
        "missing_evidence": missing,
    }


__all__ = [
    "ClosureCriterion",
    "EvidenceRecord",
    "NOT_PROVEN",
    "PROVEN",
    "SCHEMA",
    "UNMEASURABLE",
    "build_closure_matrix",
    "evaluate_criterion",
]
