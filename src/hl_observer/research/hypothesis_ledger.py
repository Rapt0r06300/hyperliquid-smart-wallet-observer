"""Append-only local research memory for Codex Discovery V3.1.

This module stores *research hypotheses and experiment metadata*, not economic
certification. It performs no network I/O and never routes orders.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
FAMILIES = frozenset({"copy_vault", "lead_lag", "cross_venue_dislocation_v2"})
STAGES = frozenset({"DISCOVERY", "TOURNAMENT", "EXPLOIT", "FREEZE", "REJECTED", "BLOCKED"})
CHANGE_CLASSES = frozenset(
    {"NEW_MECHANISM", "REPRESENTATION", "MODEL", "EXECUTION", "PARAMETER_ONLY"}
)
CONTROLLER_ACTIONS = frozenset({"IMPROVE", "COMBINE", "PIVOT", "STOP"})
_SEMANTIC_WEIGHTS = {
    "mechanism": 3.0,
    "data_surfaces": 3.0,
    "temporal_operator": 1.5,
    "conditioning": 1.0,
    "prediction_target": 1.5,
    "execution_translation": 1.0,
}
_HYPOTHESIS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RECORD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class HypothesisValidationError(ValueError):
    """Raised when a research-memory record is malformed."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _clean_text(value: Any, field_name: str, *, max_len: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HypothesisValidationError(f"{field_name} must be a non-empty string")
    text = " ".join(value.split())
    if len(text) > max_len:
        raise HypothesisValidationError(f"{field_name} exceeds {max_len} characters")
    return text


def _optional_text(value: Any, field_name: str, *, max_len: int = 4000) -> str | None:
    if value is None:
        return None
    return _clean_text(value, field_name, max_len=max_len)


def _string_list(value: Any, field_name: str, *, allow_empty: bool = True) -> list[str]:
    if value is None and allow_empty:
        return []
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        raw = list(value)
    else:
        raise HypothesisValidationError(f"{field_name} must be a string or list of strings")
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = _clean_text(item, field_name, max_len=500)
        key = text.casefold()
        if key not in seen:
            seen.add(key)
            out.append(text)
    out.sort(key=str.casefold)
    if not allow_empty and not out:
        raise HypothesisValidationError(f"{field_name} cannot be empty")
    return out


def _finite_json(value: Any, field_name: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise HypothesisValidationError(f"{field_name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        return {str(key): _finite_json(item, field_name) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_json(item, field_name) for item in value]
    raise HypothesisValidationError(
        f"{field_name} contains unsupported value {type(value).__name__}"
    )


def _validate_created_at(value: Any) -> str:
    text = _clean_text(value, "created_at_utc", max_len=64)
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise HypothesisValidationError("created_at_utc must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise HypothesisValidationError("created_at_utc must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def validate_record(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one ledger record."""
    if not isinstance(payload, Mapping):
        raise HypothesisValidationError("record must be a JSON object")
    schema_version = payload.get("schema_version", SCHEMA_VERSION)
    if schema_version != SCHEMA_VERSION:
        raise HypothesisValidationError(f"schema_version must be {SCHEMA_VERSION}")

    hypothesis_id = _clean_text(payload.get("hypothesis_id"), "hypothesis_id", max_len=128)
    if not _HYPOTHESIS_RE.fullmatch(hypothesis_id):
        raise HypothesisValidationError("hypothesis_id contains unsafe characters")

    family = payload.get("family")
    if family not in FAMILIES:
        raise HypothesisValidationError(f"family must be one of {sorted(FAMILIES)}")
    stage = payload.get("stage")
    if stage not in STAGES:
        raise HypothesisValidationError(f"stage must be one of {sorted(STAGES)}")
    change_class = payload.get("change_class")
    if change_class not in CHANGE_CLASSES:
        raise HypothesisValidationError(
            f"change_class must be one of {sorted(CHANGE_CLASSES)}"
        )

    parent = payload.get("parent_hypothesis_id")
    if parent is not None:
        parent = _clean_text(parent, "parent_hypothesis_id", max_len=128)
        if not _HYPOTHESIS_RE.fullmatch(parent):
            raise HypothesisValidationError("parent_hypothesis_id contains unsafe characters")
        if parent == hypothesis_id:
            raise HypothesisValidationError("hypothesis cannot be its own parent")

    record_id = payload.get("record_id") or f"R-{uuid.uuid4().hex}"
    record_id = _clean_text(record_id, "record_id", max_len=160)
    if not _RECORD_RE.fullmatch(record_id):
        raise HypothesisValidationError("record_id contains unsafe characters")
    created_at = _validate_created_at(payload.get("created_at_utc") or _utc_now())

    scientific_signatures = _string_list(
        payload.get("scientific_signatures", []), "scientific_signatures"
    )
    for signature in scientific_signatures:
        if not _SHA256_RE.fullmatch(signature):
            raise HypothesisValidationError(
                "scientific_signatures entries must be 64-character hex digests"
            )

    trial_count = payload.get("trial_count", 0)
    if not isinstance(trial_count, int) or isinstance(trial_count, bool) or trial_count < 0:
        raise HypothesisValidationError("trial_count must be a non-negative integer")
    baseline = payload.get("baseline", False)
    if not isinstance(baseline, bool):
        raise HypothesisValidationError("baseline must be boolean")

    base_sha = payload.get("base_sha")
    if base_sha is not None:
        base_sha = _clean_text(base_sha, "base_sha", max_len=40).lower()
        if not _GIT_SHA_RE.fullmatch(base_sha):
            raise HypothesisValidationError("base_sha must be an exact 40-character Git SHA")

    controller_action = payload.get("controller_action")
    if controller_action is not None and controller_action not in CONTROLLER_ACTIONS:
        raise HypothesisValidationError(
            f"controller_action must be one of {sorted(CONTROLLER_ACTIONS)}"
        )

    economic_progress = payload.get("economic_progress", {})
    if economic_progress is None:
        economic_progress = {}
    if not isinstance(economic_progress, Mapping):
        raise HypothesisValidationError("economic_progress must be a JSON object")
    economic_progress = _finite_json(dict(economic_progress), "economic_progress")

    return {
        "schema_version": SCHEMA_VERSION,
        "record_id": record_id,
        "created_at_utc": created_at,
        "hypothesis_id": hypothesis_id,
        "family": family,
        "parent_hypothesis_id": parent,
        "stage": stage,
        "mechanism": _clean_text(payload.get("mechanism"), "mechanism", max_len=1000),
        "data_surfaces": _string_list(
            payload.get("data_surfaces"), "data_surfaces", allow_empty=False
        ),
        "temporal_operator": _clean_text(
            payload.get("temporal_operator"), "temporal_operator", max_len=1000
        ),
        "conditioning": _string_list(payload.get("conditioning", []), "conditioning"),
        "prediction_target": _clean_text(
            payload.get("prediction_target"), "prediction_target", max_len=1000
        ),
        "execution_translation": _clean_text(
            payload.get("execution_translation"), "execution_translation", max_len=1000
        ),
        "change_class": change_class,
        "rationale": _clean_text(payload.get("rationale"), "rationale"),
        "falsification_test": _clean_text(
            payload.get("falsification_test"), "falsification_test"
        ),
        "source_refs": _string_list(payload.get("source_refs", []), "source_refs"),
        "experiment_ids": _string_list(payload.get("experiment_ids", []), "experiment_ids"),
        "scientific_signatures": [item.lower() for item in scientific_signatures],
        "trial_count": trial_count,
        "verdict": _optional_text(payload.get("verdict"), "verdict", max_len=200),
        "economic_progress": economic_progress,
        "notes": _optional_text(payload.get("notes"), "notes"),
        "baseline": baseline,
        "base_sha": base_sha,
        "controller_action": controller_action,
    }


def _normalized_semantics(record: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_record(record)

    def text(value: str) -> str:
        return " ".join(value.casefold().split())

    return {
        "mechanism": text(validated["mechanism"]),
        "data_surfaces": sorted({text(item) for item in validated["data_surfaces"]}),
        "temporal_operator": text(validated["temporal_operator"]),
        "conditioning": sorted({text(item) for item in validated["conditioning"]}),
        "prediction_target": text(validated["prediction_target"]),
        "execution_translation": text(validated["execution_translation"]),
    }


def semantic_fingerprint(record: Mapping[str, Any]) -> str:
    """Return a stable semantic digest independent of audit labels and tuning metadata."""
    payload = json.dumps(
        _normalized_semantics(record),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _jaccard_distance(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 0.0
    return 1.0 - (len(a & b) / len(a | b))


def _categorical_distance(left: str, right: str) -> float:
    return 0.0 if left == right else 1.0


def _semantic_distance(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    distances = {
        "mechanism": _categorical_distance(left["mechanism"], right["mechanism"]),
        "data_surfaces": _jaccard_distance(left["data_surfaces"], right["data_surfaces"]),
        "temporal_operator": _categorical_distance(
            left["temporal_operator"], right["temporal_operator"]
        ),
        "conditioning": _jaccard_distance(left["conditioning"], right["conditioning"]),
        "prediction_target": _categorical_distance(
            left["prediction_target"], right["prediction_target"]
        ),
        "execution_translation": _categorical_distance(
            left["execution_translation"], right["execution_translation"]
        ),
    }
    total_weight = sum(_SEMANTIC_WEIGHTS.values())
    weighted = sum(_SEMANTIC_WEIGHTS[key] * distances[key] for key in distances)
    return weighted / total_weight


def novelty_score(candidate: Mapping[str, Any], history: Iterable[Mapping[str, Any]]) -> float:
    """Measure structural distance from prior evaluated hypotheses in ``[0, 1]``."""
    candidate_semantics = _normalized_semantics(candidate)
    prior = [_normalized_semantics(item) for item in history]
    if not prior:
        return 1.0
    score = min(_semantic_distance(candidate_semantics, item) for item in prior)
    return round(min(1.0, max(0.0, score)), 6)


def append_record(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate then append exactly one JSONL record without rewriting history."""
    record = validate_record(payload)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing_ids = {item["record_id"] for item in load_records(target)}
    if record["record_id"] in existing_ids:
        raise HypothesisValidationError(f"record_id already exists: {record['record_id']}")
    encoded = (
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if len(encoded) > 1_000_000:
        raise HypothesisValidationError("one ledger record may not exceed 1 MB")
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd = os.open(target, flags, 0o600)
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)
    return record


def load_records(path: Path, family: str | None = None) -> list[dict[str, Any]]:
    """Load and validate the append-only ledger, optionally filtering by family."""
    if family is not None and family not in FAMILIES:
        raise HypothesisValidationError(f"family must be one of {sorted(FAMILIES)}")
    target = Path(path)
    if not target.exists():
        return []
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise HypothesisValidationError(f"cannot read ledger: {exc}") from exc
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HypothesisValidationError(f"invalid JSON at ledger line {lineno}") from exc
        record = validate_record(raw)
        if record["record_id"] in seen_ids:
            raise HypothesisValidationError(
                f"duplicate record_id {record['record_id']} at ledger line {lineno}"
            )
        seen_ids.add(record["record_id"])
        if family is None or record["family"] == family:
            records.append(record)
    return records


def _lineage_ids(history: list[dict[str, Any]], hypothesis_id: str) -> set[str]:
    ids = {hypothesis_id}
    changed = True
    while changed:
        changed = False
        for record in history:
            child = record["hypothesis_id"]
            parent = record.get("parent_hypothesis_id")
            if child in ids and parent and parent not in ids:
                ids.add(parent)
                changed = True
            if parent in ids and child not in ids:
                ids.add(child)
                changed = True
    return ids


def _positive_progress(record: Mapping[str, Any]) -> bool:
    progress = record.get("economic_progress")
    if not isinstance(progress, Mapping) or progress.get("comparable") is not True:
        return False
    if progress.get("improved") is True:
        return True
    for key in (
        "delta_net_usd_per_day",
        "delta_net_bps",
        "headroom_delta_usd_per_day",
        "delta_headroom_bps",
    ):
        value = progress.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return True
    return False


def _nonpositive_or_rejected(record: Mapping[str, Any]) -> bool:
    verdict = str(record.get("verdict") or "").upper()
    if verdict in {"REJECT", "REJECTED", "KILL", "NO_GO"}:
        return True
    progress = record.get("economic_progress")
    if not isinstance(progress, Mapping):
        return False
    for key in ("net_headroom_usd_per_day", "headroom_usd_per_day", "net_usd_per_day"):
        value = progress.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value <= 0:
            return True
    return False


def rediscovery_required(history: Iterable[Mapping[str, Any]], hypothesis_id: str) -> bool:
    """Return True when a research lineage has objectively stalled and should pivot."""
    normalized = [validate_record(item) for item in history]
    if not normalized:
        return False
    ids = _lineage_ids(normalized, hypothesis_id)
    lineage = [item for item in normalized if item["hypothesis_id"] in ids]
    lineage.sort(key=lambda item: (item["created_at_utc"], item["record_id"]))
    if len(lineage) >= 2:
        last_two = lineage[-2:]
        if all(item["change_class"] == "PARAMETER_ONLY" for item in last_two) and not any(
            _positive_progress(item) for item in last_two
        ):
            return True
    evaluated = [
        item
        for item in lineage
        if item["stage"] in {"TOURNAMENT", "EXPLOIT", "REJECTED", "BLOCKED"}
    ]
    if len(evaluated) >= 2 and all(_nonpositive_or_rejected(item) for item in evaluated[-2:]):
        return True
    return False


def challenger_required(history: Iterable[Mapping[str, Any]], hypothesis_id: str) -> bool:
    """Require a novelty check after three consecutive IMPROVE decisions.

    This does not reject the incumbent. It only forces a small orthogonal
    champion-challenger Discovery pass before a fourth local improvement.
    """
    normalized = [validate_record(item) for item in history]
    if not normalized:
        return False
    ids = _lineage_ids(normalized, hypothesis_id)
    lineage = [item for item in normalized if item["hypothesis_id"] in ids]
    lineage.sort(key=lambda item: (item["created_at_utc"], item["record_id"]))
    consecutive_improves = 0
    for item in reversed(lineage):
        if item["stage"] == "FREEZE":
            break
        if item.get("controller_action") == "IMPROVE":
            consecutive_improves += 1
            if consecutive_improves >= 3:
                return True
            continue
        break
    return False


def compact_status(history: Iterable[Mapping[str, Any]], family: str | None = None) -> dict[str, Any]:
    """Return a compact machine-readable research-state summary."""
    if family is not None and family not in FAMILIES:
        raise HypothesisValidationError(f"family must be one of {sorted(FAMILIES)}")
    records = [validate_record(item) for item in history]
    if family is not None:
        records = [item for item in records if item["family"] == family]
    records.sort(key=lambda item: (item["created_at_utc"], item["record_id"]))
    stage_counts = {stage: 0 for stage in sorted(STAGES)}
    change_counts = {kind: 0 for kind in sorted(CHANGE_CLASSES)}
    unique_hypotheses: set[str] = set()
    baselines = 0
    total_trials = 0
    for record in records:
        stage_counts[record["stage"]] += 1
        change_counts[record["change_class"]] += 1
        unique_hypotheses.add(record["hypothesis_id"])
        baselines += int(record["baseline"])
        total_trials += record["trial_count"]
    latest = records[-1] if records else None
    latest_id = latest["hypothesis_id"] if latest else None
    return {
        "schema_version": SCHEMA_VERSION,
        "family": family,
        "records": len(records),
        "unique_hypotheses": len(unique_hypotheses),
        "baseline_records": baselines,
        "trial_count": total_trials,
        "stage_counts": stage_counts,
        "change_class_counts": change_counts,
        "latest": (
            {
                "record_id": latest["record_id"],
                "hypothesis_id": latest_id,
                "stage": latest["stage"],
                "verdict": latest["verdict"],
                "change_class": latest["change_class"],
                "created_at_utc": latest["created_at_utc"],
                "base_sha": latest["base_sha"],
                "controller_action": latest["controller_action"],
            }
            if latest
            else None
        ),
        "rediscovery_required": (
            rediscovery_required(records, latest_id) if latest_id is not None else False
        ),
        "challenger_required": (
            challenger_required(records, latest_id) if latest_id is not None else False
        ),
    }


__all__ = [
    "CHANGE_CLASSES",
    "CONTROLLER_ACTIONS",
    "FAMILIES",
    "HypothesisValidationError",
    "SCHEMA_VERSION",
    "STAGES",
    "append_record",
    "challenger_required",
    "compact_status",
    "load_records",
    "novelty_score",
    "rediscovery_required",
    "semantic_fingerprint",
    "validate_record",
]
