"""Append-only, consultative Copy-Vault leader-review receipts.

This ledger preserves review context and its binding to a materialized SAFE
inventory. It does not rehash shard bytes, make selection decisions, or certify
economic results; canonical SAFE admission and deterministic gates remain the
authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hl_observer.alerts.durability import SingleWriterFileLock, WriterBusy
from hl_observer.research.decision_explainer import build_leader_review

SCHEMA = "copy_vault.leader_review_receipt.v1"
GENESIS_SHA256 = "0" * 64
DEFAULT_RELATIVE_PATH = Path("runtime/reports/copy_vault/leader_reviews.jsonl")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_MAX_RECEIPT_BYTES = 1_000_000
_SAFE_FAMILIES = frozenset({
    "copy_vault_fills",
    "copy_vault_l2",
    "copy_vault_snapshot",
    "copy_vault_bbo",
    "copy_vault_trades",
    "copy_vault_active_asset_ctx",
    "copy_vault_funding",
    "copy_vault_ledger",
})
_MAX_REVIEW_BATCH_ITEMS = 10_000
_MAX_REVIEW_BATCH_BYTES = 64 * 1024 * 1024
_INVENTORY_FIELDS = (
    "dataset_id", "family", "release_tag", "release_asset", "manifest_path",
    "bytes", "sha256",
)


class LeaderReviewLedgerError(ValueError):
    """Malformed, conflicting, or tampered consultative review ledger."""


def default_leader_review_path(root: str | Path) -> Path:
    """Return the Copy-Vault-only durable review ledger path under a repository root."""
    return Path(root).resolve() / DEFAULT_RELATIVE_PATH


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LeaderReviewLedgerError("REQUEST_NOT_CANONICAL_JSON") from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _inventory_digest(assets: list[Mapping[str, Any]]) -> str:
    material = "\n".join(
        "\0".join(
            str(asset.get(key) if asset.get(key) is not None else "<MISSING>")
            for key in _INVENTORY_FIELDS
        )
        for asset in assets
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _selection_digest(catalog_sha: str, assets: list[Mapping[str, Any]]) -> str:
    material = catalog_sha + "\n" + "\n".join(
        f"{asset['dataset_id']}\0{asset['sha256']}"
        for asset in sorted(assets, key=lambda row: str(row.get("dataset_id") or ""))
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _count_issue(manifest: Mapping[str, Any], field: str, issue: str) -> list[str]:
    if field not in manifest:
        return [issue + "_UNKNOWN"]
    value = manifest.get(field, 0)
    if type(value) is not int or value < 0:
        return [issue + "_INVALID"]
    return [issue] if value > 0 else []


def _validate_inventory(
    manifest: object,
) -> tuple[dict[str, Any], list[str], dict[str, dict[str, Any]]]:
    issues: list[str] = []
    if not isinstance(manifest, Mapping):
        return {}, ["SAFE_INVENTORY_MISSING"], {}

    assets_value = manifest.get("verified_source_assets")
    if (
        manifest.get("safe_catalog_status") != "SAFE_COMPLETE"
        or manifest.get("source_asset_inventory_complete") is not True
        or not isinstance(assets_value, list)
        or not assets_value
        or type(manifest.get("source_asset_inventory_count")) is not int
        or manifest.get("source_asset_inventory_count") != len(assets_value)
    ):
        issues.append("SAFE_SOURCE_ASSET_INVENTORY_MISSING_OR_INCOMPLETE")

    assets: list[Mapping[str, Any]] = []
    by_dataset: dict[str, dict[str, Any]] = {}
    for row in assets_value if isinstance(assets_value, list) else []:
        if not isinstance(row, Mapping):
            issues.append("SAFE_SOURCE_ASSET_INVENTORY_ROW_INVALID")
            continue
        dataset_id = row.get("dataset_id")
        family = row.get("family")
        digest = row.get("sha256")
        if (
            not isinstance(dataset_id, str) or not dataset_id.strip()
            or dataset_id in by_dataset
            or not isinstance(family, str) or family not in _SAFE_FAMILIES
            or type(row.get("bytes")) is not int or row["bytes"] <= 0
            or not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None
            or not all(isinstance(row.get(key), str) and row[key].strip()
                       for key in ("release_tag", "release_asset", "manifest_path"))
        ):
            issues.append("SAFE_SOURCE_ASSET_INVENTORY_ROW_INVALID")
            continue
        normalized = {
            "dataset_id": dataset_id,
            "family": family,
            "sha256": digest,
            "release_tag": row["release_tag"],
            "release_asset": row["release_asset"],
            "manifest_path": row["manifest_path"],
            "bytes": row["bytes"],
        }
        by_dataset[dataset_id] = normalized
        assets.append(row)

    catalog_sha = manifest.get("source_index_sha256")
    if not isinstance(catalog_sha, str) or _SHA256_RE.fullmatch(catalog_sha) is None:
        issues.append("SAFE_SOURCE_INDEX_SHA256_INVALID")
        catalog_sha = ""
    inventory_sha = manifest.get("source_asset_inventory_sha256")
    if (
        not isinstance(inventory_sha, str)
        or inventory_sha != _inventory_digest(assets)
    ):
        issues.append("SAFE_SOURCE_ASSET_INVENTORY_DIGEST_MISMATCH")
    selection_sha = manifest.get("selection_digest")
    if (
        not isinstance(selection_sha, str)
        or not catalog_sha
        or selection_sha != _selection_digest(catalog_sha, assets)
    ):
        issues.append("SAFE_SELECTION_DIGEST_DOES_NOT_BIND_SOURCE_INVENTORY")

    if manifest.get("data_complete") is not True:
        issues.append("SAFE_INPUTS_INCOMPLETE")
    if manifest.get("paper_read_only") is not True or manifest.get("real_execution") is not False:
        issues.append("SAFE_INPUT_EXECUTION_GUARD_INVALID")
    for field, code in (
        ("missing_shards", "SAFE_SHARDS_MISSING"),
        ("rejected_assets", "SAFE_SHARDS_REJECTED"),
        ("continuity_evidence_missing_shards", "SAFE_CONTINUITY_EVIDENCE_MISSING"),
        ("payload_rejected_records", "SAFE_PAYLOAD_ROWS_REJECTED"),
    ):
        issues.extend(_count_issue(manifest, field, code))
    historical = manifest.get("historical_coverage_audit")
    if historical is None:
        issues.append("HISTORICAL_COVERAGE_UNKNOWN")
    elif not isinstance(historical, Mapping) or historical.get("status") != "COMPLETE":
        issues.append("HISTORICAL_COVERAGE_INCOMPLETE")

    binding = {
        "safe_catalog_status": str(manifest.get("safe_catalog_status") or "UNKNOWN"),
        "source_index_sha256": catalog_sha,
        "selection_digest": str(manifest.get("selection_digest") or ""),
        "source_asset_inventory_sha256": str(inventory_sha or ""),
        "source_asset_inventory_count": len(assets),
        "data_complete": manifest.get("data_complete") is True,
    }
    return binding, sorted(set(issues)), by_dataset


def _bind_review_evidence(
    review_payload: Mapping[str, Any],
    *,
    inventory_catalog_sha: str,
    by_dataset: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, str]], list[str]]:
    rows = review_payload.get("evidence")
    if not isinstance(rows, (list, tuple)):
        return [], ["SAFE_EVIDENCE_ROWS_INVALID"]
    bindings: list[dict[str, str]] = []
    issues: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            issues.append(f"SAFE_EVIDENCE_{index}_INVALID")
            continue
        dataset_id = row.get("source_dataset_id")
        family = row.get("source_family")
        shard_sha = row.get("source_sha256")
        catalog_sha = row.get("source_catalog_sha256")
        if not isinstance(dataset_id, str) or dataset_id not in by_dataset:
            issues.append(f"SAFE_EVIDENCE_{index}_DATASET_NOT_IN_INVENTORY")
            continue
        asset = by_dataset[dataset_id]
        source = row.get("source")
        if source != asset["family"]:
            issues.append(f"SAFE_EVIDENCE_{index}_SOURCE_MISMATCH")
        if family != asset["family"]:
            issues.append(f"SAFE_EVIDENCE_{index}_FAMILY_MISMATCH")
        if shard_sha != asset["sha256"]:
            issues.append(f"SAFE_EVIDENCE_{index}_SHA256_MISMATCH")
        if catalog_sha != inventory_catalog_sha:
            issues.append(f"SAFE_EVIDENCE_{index}_CATALOG_MISMATCH")
        if (
            family == asset["family"]
            and source == asset["family"]
            and shard_sha == asset["sha256"]
            and catalog_sha == inventory_catalog_sha
        ):
            bindings.append({
                "ref": str(row.get("ref") or ""),
                "dataset_id": dataset_id,
                "family": asset["family"],
                "sha256": asset["sha256"],
                "source_catalog_sha256": catalog_sha,
                "release_tag": str(asset["release_tag"]),
                "release_asset": str(asset["release_asset"]),
                "manifest_path": str(asset["manifest_path"]),
                "bytes": asset["bytes"],
            })
    return bindings, issues


def _incident_codes(issues: list[str]) -> list[dict[str, str]]:
    incidents = []
    for issue in sorted(set(issues)):
        if "STALE" in issue:
            category = "STALE_EVIDENCE"
        elif "CONTRADICTORY" in issue:
            category = "CONTRADICTORY_FINDINGS"
        elif "COVERAGE" in issue or "MISSING" in issue or "INCOMPLETE" in issue:
            category = "COVERAGE_OR_MISSING_EVIDENCE"
        elif "SHA256" in issue or "DIGEST" in issue or "CATALOG" in issue:
            category = "PROVENANCE_MISMATCH"
        else:
            category = "REVIEW_INVALID"
        incidents.append({"code": issue, "category": category})
    return incidents


def _receipt_digest(record: Mapping[str, Any]) -> str:
    body = {key: value for key, value in record.items() if key != "receipt_sha256"}
    return _sha256(body)


def _load_unlocked(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink():
        raise LeaderReviewLedgerError("LEDGER_SYMLINK_REFUSED")
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise LeaderReviewLedgerError("LEDGER_UNREADABLE") from exc
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    previous = GENESIS_SHA256
    for line_number, line in enumerate(lines, 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LeaderReviewLedgerError(f"LEDGER_JSON_INVALID:{line_number}") from exc
        if not isinstance(record, dict) or record.get("schema") != SCHEMA:
            raise LeaderReviewLedgerError(f"LEDGER_SCHEMA_INVALID:{line_number}")
        review_id = record.get("review_id")
        if not isinstance(review_id, str) or review_id in seen:
            raise LeaderReviewLedgerError(f"LEDGER_REVIEW_ID_INVALID_OR_DUPLICATE:{line_number}")
        if record.get("previous_receipt_sha256") != previous:
            raise LeaderReviewLedgerError(f"RECEIPT_CHAIN_MISMATCH:{line_number}")
        actual = record.get("receipt_sha256")
        if not isinstance(actual, str) or _SHA256_RE.fullmatch(actual) is None:
            raise LeaderReviewLedgerError(f"RECEIPT_HASH_INVALID:{line_number}")
        try:
            expected = _receipt_digest(record)
        except LeaderReviewLedgerError as exc:
            raise LeaderReviewLedgerError(f"RECEIPT_CONTENT_INVALID:{line_number}") from exc
        if actual != expected:
            raise LeaderReviewLedgerError(f"RECEIPT_HASH_MISMATCH:{line_number}")
        if (
            record.get("consultative_only") is not True
            or record.get("can_change_decision") is not False
            or record.get("can_modify_frozen_candidate") is not False
            or record.get("can_modify_oos_forward_splits") is not False
            or record.get("can_select_champion") is not False
            or record.get("can_prove_pnl") is not False
            or record.get("real_execution") is not False
        ):
            raise LeaderReviewLedgerError(f"LEDGER_AUTHORITY_GUARD_INVALID:{line_number}")
        seen.add(review_id)
        previous = actual
        records.append(record)
    return records


def load_leader_reviews(path: str | Path) -> list[dict[str, Any]]:
    """Load the complete ledger or fail closed on malformed/tampered history."""
    return _load_unlocked(Path(path))


def summarize_leader_reviews(
    path: str | Path,
    *,
    recent_limit: int = 50,
) -> dict[str, Any]:
    """Return a compact report projection; ledger corruption is visible, never hidden."""
    target = Path(path)
    if type(recent_limit) is not int or recent_limit <= 0:
        raise LeaderReviewLedgerError("RECENT_LIMIT_INVALID")
    try:
        records = load_leader_reviews(target)
    except LeaderReviewLedgerError as exc:
        return {
            "status": "INVALID",
            "ledger_path": str(target),
            "receipt_count": None,
            "reviewable_count": None,
            "unmeasurable_count": None,
            "incident_count": None,
            "error": str(exc),
            "recent_receipts": [],
        }
    brief = []
    for record in records[-recent_limit:]:
        review = record.get("review")
        review = review if isinstance(review, Mapping) else {}
        favorable = review.get("favorable")
        favorable = [item for item in favorable if isinstance(item, Mapping)] if isinstance(favorable, list) else []
        counterevidence = review.get("counterevidence")
        counterevidence = (
            [item for item in counterevidence if isinstance(item, Mapping)]
            if isinstance(counterevidence, list) else []
        )
        unknowns = review.get("unknowns")
        unknowns = [item for item in unknowns if isinstance(item, str)] if isinstance(unknowns, list) else []
        brief.append({
            "review_id": record.get("review_id"),
            "reviewed_at_utc": record.get("reviewed_at_utc"),
            "reviewer_id": record.get("reviewer_id"),
            "leader_id": review.get("leader_id"),
            "outcome": review.get("outcome_observed"),
            "as_of_ms": review.get("as_of_ms"),
            "review_status": record.get("review_status"),
            "issues": list(record.get("issues") or []),
            "favorable": favorable[:20],
            "favorable_omitted_count": max(0, len(favorable) - 20),
            "counterevidence": counterevidence[:20],
            "counterevidence_omitted_count": max(0, len(counterevidence) - 20),
            "unknowns": unknowns[:20],
            "unknowns_omitted_count": max(0, len(unknowns) - 20),
            "falsification_condition": review.get("falsification_condition"),
            "incident_count": len(record.get("incidents") or []),
            "safe_evidence_assets": list(record.get("safe_evidence_assets") or []),
            "source_asset_inventory_sha256": (
                record.get("safe_inventory", {}).get("source_asset_inventory_sha256")
                if isinstance(record.get("safe_inventory"), Mapping) else None
            ),
        })
    return {
        "status": "AVAILABLE" if records else "EMPTY",
        "ledger_path": str(target),
        "receipt_count": len(records),
        "reviewable_count": sum(
            row.get("review_status") == "CONSULTATIVE_REVIEWABLE" for row in records
        ),
        "unmeasurable_count": sum(
            row.get("review_status") != "CONSULTATIVE_REVIEWABLE" for row in records
        ),
        "incident_count": sum(len(row.get("incidents") or []) for row in records),
        "error": None,
        "recent_receipts": brief,
    }


def _prepare_review_record(
    request: Mapping[str, Any],
    *,
    reviewer: str,
    inventory_binding: Mapping[str, Any],
    inventory_issues: list[str],
    by_dataset: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    review_payload = request.get("review_payload")
    if not isinstance(review_payload, Mapping):
        raise LeaderReviewLedgerError("REVIEW_PAYLOAD_INVALID")
    raw_context = request.get("context")
    if raw_context is not None and not isinstance(raw_context, Mapping):
        raise LeaderReviewLedgerError("REVIEW_CONTEXT_INVALID")
    context = dict(raw_context) if isinstance(raw_context, Mapping) else None
    if context is not None:
        _canonical_bytes(context)
    if inventory_issues:
        safe_evidence_assets, evidence_binding_issues = [], []
    else:
        safe_evidence_assets, evidence_binding_issues = _bind_review_evidence(
            review_payload,
            inventory_catalog_sha=str(inventory_binding.get("source_index_sha256") or ""),
            by_dataset=by_dataset,
        )
    try:
        review = build_leader_review(**dict(review_payload))
    except (TypeError, ValueError):
        review = {
            "schema_version": "copy_vault.leader_review.v1",
            "leader_id": "",
            "review_status": "UNMEASURABLE",
            "issues": ["LEADER_REVIEW_PAYLOAD_INVALID"],
            "consultative_only": True,
            "can_change_decision": False,
            "can_modify_frozen_candidate": False,
            "can_modify_oos_forward_splits": False,
            "can_select_champion": False,
            "can_prove_pnl": False,
        }

    issues = sorted(set(
        list(review.get("issues") or [])
        + inventory_issues
        + evidence_binding_issues
        + ([] if reviewer else ["REVIEWER_ID_MISSING"])
    ))
    review_status = (
        "CONSULTATIVE_REVIEWABLE"
        if review.get("review_status") == "CONSULTATIVE_REVIEWABLE" and not issues
        else "UNMEASURABLE"
    )
    digest_payload: dict[str, Any] = {
        "review_payload": dict(review_payload),
        "reviewer_id": reviewer,
        "safe_inventory_binding": dict(inventory_binding),
        "safe_inventory_issues": inventory_issues,
    }
    if context is not None:
        digest_payload["context"] = context
    request_sha = _sha256(digest_payload)
    review_id = request.get("review_id")
    resolved_id = review_id or f"LR-{request_sha[:32]}"
    if not isinstance(resolved_id, str) or _ID_RE.fullmatch(resolved_id) is None:
        raise LeaderReviewLedgerError("REVIEW_ID_INVALID")

    record: dict[str, Any] = {
        "schema": SCHEMA,
        "review_id": resolved_id,
        "request_sha256": request_sha,
        "reviewed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "reviewer_id": reviewer or None,
        "review_status": review_status,
        "review": review,
        "issues": issues,
        "incidents": _incident_codes(issues),
        "safe_inventory": dict(inventory_binding),
        "safe_evidence_assets": safe_evidence_assets,
        "safe_inventory_source_bytes_rehashed_here": False,
        "safe_inventory_requires_canonical_lab_audit": True,
        "consultative_only": True,
        "decision_authority": "CANONICAL_DETERMINISTIC_GATES_ONLY",
        "can_change_decision": False,
        "can_modify_frozen_candidate": False,
        "can_modify_oos_forward_splits": False,
        "can_select_champion": False,
        "can_prove_pnl": False,
        "paper_read_only": True,
        "real_execution": False,
    }
    if context is not None:
        record["context"] = context
    return record


def append_leader_review_batch(
    path: str | Path,
    requests: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    *,
    safe_inventory: Mapping[str, Any] | None,
    reviewer_id: str,
) -> dict[str, Any]:
    """Append many immutable reviews while loading/locking the chain only once."""
    if not isinstance(requests, (list, tuple)):
        raise LeaderReviewLedgerError("REVIEW_BATCH_INVALID")
    if len(requests) > _MAX_REVIEW_BATCH_ITEMS:
        raise LeaderReviewLedgerError("REVIEW_BATCH_ITEM_LIMIT_EXCEEDED")
    reviewer = reviewer_id.strip() if isinstance(reviewer_id, str) else ""
    inventory_binding, inventory_issues, by_dataset = _validate_inventory(safe_inventory)
    prepared = [
        _prepare_review_record(
            request,
            reviewer=reviewer,
            inventory_binding=inventory_binding,
            inventory_issues=inventory_issues,
            by_dataset=by_dataset,
        )
        for request in requests
    ]
    if not prepared:
        return {"records": [], "created_count": 0, "reused_count": 0}
    target = Path(path)
    if target.is_symlink():
        raise LeaderReviewLedgerError("LEDGER_SYMLINK_REFUSED")
    lock_path = target.with_suffix(target.suffix + ".lock")
    if lock_path.is_symlink():
        raise LeaderReviewLedgerError("LEDGER_LOCK_SYMLINK_REFUSED")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with SingleWriterFileLock(lock_path):
            existing = _load_unlocked(target)
            existing_by_id = {row["review_id"]: row for row in existing}
            queued_by_id: dict[str, dict[str, Any]] = {}
            results: list[dict[str, Any] | None] = [None] * len(prepared)
            new_records: list[dict[str, Any]] = []
            for index, record in enumerate(prepared):
                review_id = record["review_id"]
                request_sha = record["request_sha256"]
                prior = existing_by_id.get(review_id)
                if prior is not None:
                    if prior.get("request_sha256") != request_sha:
                        raise LeaderReviewLedgerError("REVIEW_ID_CONFLICT")
                    results[index] = prior
                    continue
                queued = queued_by_id.get(review_id)
                if queued is not None:
                    if queued.get("request_sha256") != request_sha:
                        raise LeaderReviewLedgerError("REVIEW_ID_CONFLICT")
                    results[index] = queued
                    continue
                queued_by_id[review_id] = record
                new_records.append(record)

            previous = existing[-1]["receipt_sha256"] if existing else GENESIS_SHA256
            encoded_rows: list[bytes] = []
            total_bytes = 0
            for record in new_records:
                record["previous_receipt_sha256"] = previous
                record["receipt_sha256"] = _receipt_digest(record)
                encoded = _canonical_bytes(record) + b"\n"
                if len(encoded) > _MAX_RECEIPT_BYTES:
                    raise LeaderReviewLedgerError("RECEIPT_SIZE_LIMIT_EXCEEDED")
                total_bytes += len(encoded)
                if total_bytes > _MAX_REVIEW_BATCH_BYTES:
                    raise LeaderReviewLedgerError("REVIEW_BATCH_SIZE_LIMIT_EXCEEDED")
                encoded_rows.append(encoded)
                previous = record["receipt_sha256"]
            for index, record in enumerate(prepared):
                if results[index] is None:
                    results[index] = queued_by_id[record["review_id"]]
            if not new_records:
                return {
                    "records": [row for row in results if row is not None],
                    "created_count": 0,
                    "reused_count": len(results),
                }
            flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY
            fd = os.open(target, flags, 0o600)
            try:
                remaining = memoryview(b"".join(encoded_rows))
                while remaining:
                    written = os.write(fd, remaining)
                    if written <= 0:
                        raise LeaderReviewLedgerError("LEDGER_APPEND_INCOMPLETE")
                    remaining = remaining[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            return {
                "records": [row for row in results if row is not None],
                "created_count": len(new_records),
                "reused_count": len(results) - len(new_records),
            }
    except WriterBusy as exc:
        raise LeaderReviewLedgerError("LEDGER_WRITER_BUSY") from exc


def append_leader_review(
    path: str | Path,
    review_payload: Mapping[str, Any],
    *,
    safe_inventory: Mapping[str, Any] | None,
    reviewer_id: str,
    review_id: str | None = None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one immutable consultative review, including unmeasurable receipts."""
    request: dict[str, Any] = {"review_payload": review_payload}
    if review_id is not None:
        request["review_id"] = review_id
    if context is not None:
        request["context"] = context
    result = append_leader_review_batch(
        path, [request], safe_inventory=safe_inventory, reviewer_id=reviewer_id,
    )
    return result["records"][0]


def append_copy_vault_v9_leader_reviews(
    path: str | Path,
    analysis: Mapping[str, Any],
    *,
    safe_inventory: Mapping[str, Any] | None,
    reviewer_id: str,
    max_evidence_age_ms: int,
    engine_sha256: str,
) -> dict[str, Any]:
    """Persist every V9 TRAIN leader decision as consultative, SAFE-bound evidence."""
    if (
        not isinstance(analysis, Mapping)
        or analysis.get("schema_version")
        != "hypersmart.copy_vault_v9_online_leader_quality_train.v1"
        or analysis.get("selection_scope") != "TRAIN_ONLY_PRE_FREEZE"
        or analysis.get("heldout_evaluated") is not False
        or isinstance(max_evidence_age_ms, bool)
        or not isinstance(max_evidence_age_ms, int)
        or max_evidence_age_ms <= 0
        or not isinstance(engine_sha256, str)
        or _SHA256_RE.fullmatch(engine_sha256) is None
    ):
        raise LeaderReviewLedgerError("V9_TRAIN_DECISION_SCOPE_INVALID")
    traces = analysis.get("leader_decision_traces")
    if (
        not isinstance(traces, Mapping)
        or traces.get("schema_version") != "copy_vault.leader_quality_decision_trace.v1"
        or traces.get("scope") != "TRAIN_ONLY_PRE_FREEZE"
        or not isinstance(traces.get("traces"), list)
    ):
        raise LeaderReviewLedgerError("V9_TRAIN_DECISION_TRACES_INVALID")

    requests: list[dict[str, Any]] = []
    selection_digest = str(
        safe_inventory.get("selection_digest") or ""
    ) if isinstance(safe_inventory, Mapping) else ""
    source_catalog_sha256 = str(
        safe_inventory.get("source_index_sha256") or ""
    ) if isinstance(safe_inventory, Mapping) else ""
    for trace_index, trace in enumerate(traces["traces"]):
        if (
            not isinstance(trace, Mapping)
            or not isinstance(trace.get("decisions"), list)
            or type(trace.get("candidate_decision_count")) is not int
            or trace["candidate_decision_count"] != len(trace["decisions"])
        ):
            raise LeaderReviewLedgerError(f"V9_TRAIN_TRACE_INVALID:{trace_index}")
        parameters = {
            "minimum_prior_closed": trace.get("minimum_prior_closed"),
            "history_window": trace.get("history_window"),
        }
        for decision_index, decision in enumerate(trace["decisions"]):
            if not isinstance(decision, Mapping):
                raise LeaderReviewLedgerError(
                    f"V9_TRAIN_DECISION_INVALID:{trace_index}:{decision_index}"
                )
            outcome = decision.get("outcome")
            raw_evidence = decision.get("evidence_refs")
            evidence = list(raw_evidence) if isinstance(raw_evidence, (list, tuple)) else []
            valid_refs = [
                row["ref"] for row in evidence
                if isinstance(row, Mapping)
                and isinstance(row.get("ref"), str)
                and row["ref"].strip()
            ]
            evidence_complete = (
                decision.get("evidence_status") == "SAFE_CAUSAL_COMPLETE"
                and len(valid_refs) == len(evidence)
                and bool(valid_refs)
            )
            reason = str(decision.get("reason") or "DECISION_REASON_UNKNOWN")
            prior_count = decision.get("prior_count")
            prior_mean = decision.get("prior_mean_net_pnl_usd")
            favorable: list[dict[str, Any]] = []
            counterevidence: list[dict[str, Any]] = []
            unknowns = [f"Raison de la décision TRAIN : {reason}."]
            if type(prior_count) is int:
                unknowns.append(f"Historique antérieur fermé disponible : {prior_count} trade(s).")
            if evidence_complete and outcome == "RETAINED":
                favorable.append({
                    "finding_key": "causal_prior_net_mean",
                    "summary": (
                        f"Moyenne nette antérieure observée : {prior_mean} USD; "
                        f"{prior_count} trade(s), décision TRAIN uniquement."
                    ),
                    "evidence_refs": valid_refs,
                })
                unknowns.append("La généralisation hors TRAIN et la capacité forward restent inconnues.")
            elif evidence_complete and outcome == "DEMOTED":
                counterevidence.append({
                    "finding_key": "causal_prior_net_mean",
                    "summary": (
                        f"Moyenne nette antérieure observée : {prior_mean} USD; "
                        f"{prior_count} trade(s), décision TRAIN uniquement."
                    ),
                    "evidence_refs": valid_refs,
                })
                unknowns.append("La récupération future du leader n’est pas évaluée par cette revue.")
            else:
                unknowns.append(
                    "Preuves causales SAFE absentes, incomplètes ou insuffisamment fraîches; "
                    "aucune conclusion favorable ou défavorable supplémentaire n’est ajoutée."
                )
            candidate_id = str(
                decision.get("candidate_trade_id") or "UNKNOWN_CANDIDATE"
            )
            payload = {
                "leader_id": decision.get("leader_id"),
                "outcome": outcome,
                "as_of_ms": decision.get("as_of_ms"),
                "max_evidence_age_ms": max_evidence_age_ms,
                "favorable": favorable,
                "counterevidence": counterevidence,
                "unknowns": unknowns,
                "falsification_condition": (
                    "Réviser si une nouvelle reconstruction causale TRAIN, liée au même "
                    "corpus et au même as-of, ne reproduit pas la décision; toute preuve "
                    "future doit rester séparée des splits gelés."
                ),
                "evidence": evidence,
            }
            context = {
                "decision_scope": decision.get("decision_scope"),
                "candidate_trade_id": candidate_id,
                "trace_parameters": parameters,
                "reason": reason,
                "prior_count": prior_count,
                "prior_mean_net_pnl_usd": prior_mean,
                "evidence_status": decision.get("evidence_status"),
                "selection_digest": selection_digest,
                "source_catalog_sha256": source_catalog_sha256,
                "engine_sha256": engine_sha256,
                "train_scope": "TRAIN_ONLY_PRE_FREEZE",
                "heldout_evaluated": False,
            }
            requests.append({"review_payload": payload, "context": context})

    batch = append_leader_review_batch(
        path, requests, safe_inventory=safe_inventory, reviewer_id=reviewer_id,
    )
    records = batch["records"]
    reviewable_count = sum(
        record.get("review_status") == "CONSULTATIVE_REVIEWABLE" for record in records
    )
    return {
        "status": "PERSISTED" if records else "NO_LEADER_DECISIONS",
        "decision_count": len(records),
        "created_count": batch["created_count"],
        "reused_count": batch["reused_count"],
        "reviewable_count": reviewable_count,
        "unmeasurable_count": len(records) - reviewable_count,
        "ledger_path": str(Path(path)),
        "receipt_sha256": records[-1].get("receipt_sha256") if records else None,
        "review_ids": [record["review_id"] for record in records],
        "consultative_only": True,
        "can_change_decision": False,
        "can_modify_frozen_candidate": False,
        "can_modify_oos_forward_splits": False,
        "can_select_champion": False,
        "can_prove_pnl": False,
    }


__all__ = [
    "DEFAULT_RELATIVE_PATH",
    "GENESIS_SHA256",
    "LeaderReviewLedgerError",
    "append_copy_vault_v9_leader_reviews",
    "append_leader_review",
    "append_leader_review_batch",
    "default_leader_review_path",
    "load_leader_reviews",
    "summarize_leader_reviews",
]
