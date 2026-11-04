from __future__ import annotations

import hashlib
import json
import math
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hl_observer.datasets.dataset_untrusted_guard import assert_workspace_safe
from hl_observer.datasets.github_release_bridge import DatasetBridgeError

REQUIRED_TOOL_FILES = (
    "pipeline_copie_reel.py",
    "backtest_dislocation_2jambes.py",
)


def deduplicate_release_sessions(sessions: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """Keep the first verified session for each release/tag identity."""
    rows = list(sessions)
    kept: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            return {"status": "UNMEASURABLE", "reason": "SESSION_INVALID"}
        key = (str(raw.get("release_id") or ""), str(raw.get("tag_name") or ""))
        if not key[0] or not key[1]:
            return {"status": "UNMEASURABLE", "reason": "SESSION_IDENTITY_MISSING"}
        if key in seen:
            continue
        seen.add(key)
        kept.append(dict(raw))
    return {"status": "PROVEN", "input_count": len(rows), "unique_count": len(kept), "sessions": kept}


def default_materialized_root(project_root: Path) -> Path:
    return project_root / "data" / "hypersmart_datasets" / "materialized"


def prepare_replay_workspace(
    project_root: Path,
    *,
    materialized_root: Path | None = None,
) -> dict[str, object]:
    project_root = project_root.resolve()
    workspace = (materialized_root or default_materialized_root(project_root)).resolve()

    # The public contract reports a missing/unprepared FULL/COLD workspace as a
    # dataset bridge error. Do this before the untrusted-content scan so callers
    # get the actionable reconstruction message instead of a lower-level guard
    # exception when there is simply nothing to inspect yet.
    runtime_data = workspace / "runtime" / "data"
    if not workspace.is_dir() or not runtime_data.is_dir():
        raise DatasetBridgeError(
            "Aucune donnée reconstruite dans l'espace FULL/COLD. "
            "Prépare d'abord le lot économique avec dataset_bridge."
        )

    # FULL/COLD is untrusted input. Once a workspace exists, reject symlinks/
    # reparse points and any script/executable supplied by the dataset before
    # executing a project tool. On a resumed workspace, only our two previously
    # copied tools are allowed, and only when their SHA-256 still matches the
    # current project source.
    trusted_tools: dict[str, str] = {}
    for name in REQUIRED_TOOL_FILES:
        source = project_root / "tools" / name
        if source.is_file():
            trusted_tools[f"tools/{name}"] = hashlib.sha256(source.read_bytes()).hexdigest()
    untrusted_guard = assert_workspace_safe(workspace, trusted_file_sha256=trusted_tools)

    workspace_tools = workspace / "tools"
    workspace_tools.mkdir(parents=True, exist_ok=True)
    copied_tools: list[str] = []
    for name in REQUIRED_TOOL_FILES:
        source = project_root / "tools" / name
        if not source.is_file():
            raise DatasetBridgeError(f"Outil du projet introuvable: {source}")
        destination = workspace_tools / name
        shutil.copy2(source, destination)
        copied_tools.append(str(destination))

    report_dir = workspace / "runtime" / "reports" / "datasets"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "hypersmart.dataset_replay_workspace.v2",
        "project_root": str(project_root),
        "workspace_root": str(workspace),
        "runtime_data": str(runtime_data),
        "copied_tools": copied_tools,
        "untrusted_dataset_guard": untrusted_guard,
        "paper_only": True,
        "real_execution": False,
        "mainnet_execution": False,
        "testnet_execution": False,
        "status": "READY",
    }
    report_path = report_dir / "ESPACE_REPLAY.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {**report, "report_path": str(report_path)}


def _workspace_base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _workspace_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _workspace_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def replay_workspace_safety_receipt(report: Mapping[str, Any]) -> dict[str, Any]:
    valid = (
        isinstance(report, Mapping)
        and report.get("status") == "READY"
        and report.get("paper_only") is True
        and report.get("real_execution") is False
        and report.get("mainnet_execution") is False
        and report.get("testnet_execution") is False
        and isinstance(report.get("untrusted_dataset_guard"), Mapping)
    )
    return _workspace_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_WORKSPACE_SAFE" if valid else "REPLAY_WORKSPACE_UNSAFE", fail_closed=not valid)


def replay_workspace_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _workspace_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_WORKSPACE_FIELD_PRESENT" if valid else "REPLAY_WORKSPACE_FIELD_MISSING", field=field, fail_closed=not valid)


def replay_workspace_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _workspace_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_WORKSPACE_FIELD_NON_NULL" if valid else "REPLAY_WORKSPACE_FIELD_NULL", field=field, fail_closed=not valid)


def replay_workspace_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _workspace_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_WORKSPACE_FIELD_TYPE_VALID" if valid else "REPLAY_WORKSPACE_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def replay_workspace_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _workspace_finite(value)
    return _workspace_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_WORKSPACE_VALUE_FINITE" if valid else "REPLAY_WORKSPACE_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def replay_workspace_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _workspace_integer(event_ts_ms) and _workspace_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _workspace_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_WORKSPACE_EVENT_WITHIN_CUTOFF" if valid else "REPLAY_WORKSPACE_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def replay_workspace_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _workspace_integer(event_ts_ms) and _workspace_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _workspace_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_WORKSPACE_EVENT_AGE_VALID" if valid else "REPLAY_WORKSPACE_EVENT_TOO_OLD", fail_closed=not valid)


def replay_workspace_duplicate_receipt(*, event_ids: list[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _workspace_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_WORKSPACE_EVENTS_UNIQUE" if valid else "REPLAY_WORKSPACE_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def replay_workspace_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _workspace_integer(attempts) and _workspace_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _workspace_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_WORKSPACE_RETRY_BOUNDED" if valid else "REPLAY_WORKSPACE_RETRY_UNSAFE", fail_closed=not valid)


def replay_workspace_replay_receipt(*, outputs: list[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _workspace_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_WORKSPACE_REPLAY_DETERMINISTIC" if valid else "REPLAY_WORKSPACE_REPLAY_DIVERGED", fail_closed=not valid)


def replay_workspace_http_error_receipt(*, status_code: Any, retry_after_seconds: Any = None) -> dict[str, Any]:
    valid_status = _workspace_integer(status_code) and status_code in {404, 408, 429, 500, 502, 503, 504}
    retryable = status_code in {408, 429, 500, 502, 503, 504} and _workspace_finite(retry_after_seconds) and float(retry_after_seconds) > 0
    valid = status_code == 404 or retryable
    return _workspace_base("PROVEN" if valid and valid_status else "REJECTED", verdict="REPLAY_WORKSPACE_REMOTE_ERROR_QUARANTINED" if valid and valid_status else "REPLAY_WORKSPACE_REMOTE_ERROR_UNSAFE", status_code=status_code, retryable=retryable, fail_closed=not (valid and valid_status))


def replay_workspace_range_receipt(*, requested_start: Any, observed_start: Any, range_honored: bool) -> dict[str, Any]:
    valid = _workspace_integer(requested_start) and _workspace_integer(observed_start) and requested_start == observed_start and range_honored is True
    return _workspace_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_WORKSPACE_RANGE_HONORED" if valid else "REPLAY_WORKSPACE_RANGE_IGNORED", fail_closed=not valid)


def replay_workspace_content_range_receipt(*, expected_start: Any, observed_start: Any, expected_end: Any, observed_end: Any) -> dict[str, Any]:
    valid = all(_workspace_integer(value) for value in (expected_start, observed_start, expected_end, observed_end)) and expected_start == observed_start and expected_end == observed_end and observed_end >= observed_start
    return _workspace_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_WORKSPACE_CONTENT_RANGE_MATCH" if valid else "REPLAY_WORKSPACE_CONTENT_RANGE_MISMATCH", fail_closed=not valid)


def replay_workspace_etag_receipt(*, previous_etag: Any, current_etag: Any) -> dict[str, Any]:
    previous = str(previous_etag or "").strip(); current = str(current_etag or "").strip()
    changed = bool(previous and current and previous != current)
    return _workspace_base("PROVEN" if changed else "REJECTED", verdict="REPLAY_WORKSPACE_ETAG_CHANGE_INVALIDATES_CACHE" if changed else "REPLAY_WORKSPACE_ETAG_CHANGE_UNPROVEN", cache_invalidated=changed, fail_closed=not changed)


def replay_workspace_disk_space_receipt(*, required_bytes: Any, available_bytes: Any) -> dict[str, Any]:
    valid = _workspace_integer(required_bytes) and _workspace_integer(available_bytes) and required_bytes >= 0 and available_bytes >= 0 and available_bytes >= required_bytes
    return _workspace_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_WORKSPACE_DISK_SPACE_SUFFICIENT" if valid else "REPLAY_WORKSPACE_DISK_SPACE_INSUFFICIENT", fail_closed=not valid)


def replay_workspace_zip_slip_receipt(member: Any) -> dict[str, Any]:
    text = str(member or "").replace("\\", "/")
    unsafe = text.startswith("/") or ":" in text.split("/")[0] or ".." in text.split("/")
    return _workspace_base("PROVEN" if unsafe else "REJECTED", verdict="REPLAY_WORKSPACE_ZIP_SLIP_REFUSED" if unsafe else "REPLAY_WORKSPACE_ZIP_SLIP_NOT_REFUSED", fail_closed=not unsafe)


def replay_workspace_expansion_receipt(*, observed_bytes: Any, max_bytes: Any, complete: bool) -> dict[str, Any]:
    valid = _workspace_integer(observed_bytes) and _workspace_integer(max_bytes) and observed_bytes >= 0 and max_bytes >= 0 and observed_bytes <= max_bytes and complete is True
    return _workspace_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_WORKSPACE_EXPANSION_BOUNDED" if valid else "REPLAY_WORKSPACE_EXPANSION_UNSAFE", fail_closed=not valid)


def replay_workspace_lease_receipt(*, active_leases: Any, lease_token_present: bool) -> dict[str, Any]:
    valid = _workspace_integer(active_leases) and active_leases == 1 and lease_token_present is True
    return _workspace_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_WORKSPACE_SINGLE_LEASE" if valid else "REPLAY_WORKSPACE_SPLIT_BRAIN_RISK", fail_closed=not valid)


def replay_workspace_preflight_receipt(report: Mapping[str, Any]) -> dict[str, Any]:
    return replay_workspace_safety_receipt(report)
