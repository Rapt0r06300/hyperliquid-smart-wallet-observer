#!/usr/bin/env python3
"""Read durable same-epoch Copy-Vault fill checkpoints from campaign receipts."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_ADDRESS = re.compile(r"0x[0-9a-f]{40}\Z")
_HISTORICAL_BACKFILL_AUDIT_SCHEMA = "alina.copy_vault.historical_backfill_audit.v1"
_MAX_HISTORY_AUDIT_BYTES = 1_048_576


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _history_reports_from_payload(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Read a hash-bound structured audit, or a complete legacy JSON stdout."""
    metrics = payload.get("collection_metrics")
    if isinstance(metrics, Mapping) and "historical_backfill_audit" in metrics:
        audit = metrics.get("historical_backfill_audit")
        if not isinstance(audit, Mapping):
            return None
        reports = audit.get("reports")
        if (
            audit.get("schema") != _HISTORICAL_BACKFILL_AUDIT_SCHEMA
            or audit.get("source") != "BUNDLE_INDEX.json"
            or audit.get("status") != "COMPLETE"
            or not isinstance(reports, Mapping)
            or type(audit.get("report_count")) is not int
            or audit.get("report_count") != len(reports)
            or any(
                not isinstance(address, str) or not isinstance(report, Mapping)
                for address, report in reports.items()
            )
            or audit.get("reports_sha256") != _digest(dict(reports))
        ):
            return None
        serialized = json.dumps(
            dict(reports),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        if len(serialized) > _MAX_HISTORY_AUDIT_BYTES:
            return None
        reports_bytes = audit.get("reports_bytes")
        if type(reports_bytes) is int and reports_bytes != len(serialized):
            return None
        return reports

    raw_stdout = payload.get("stdout")
    if not isinstance(raw_stdout, str):
        return None
    try:
        summary = json.loads(raw_stdout)
    except (TypeError, json.JSONDecodeError):
        return None
    reports = summary.get("historical_backfill") if isinstance(summary, Mapping) else None
    return reports if isinstance(reports, Mapping) else None


def _read_json(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _checkpoint_from_report(
    campaign: Mapping[str, Any],
    report: Mapping[str, Any],
) -> dict[str, Any] | None:
    request_status = report.get("request_audit_status", report.get("status"))
    start_ms = report.get("requested_start_ms")
    end_ms = report.get("requested_end_ms")
    oldest_fill_ms = report.get("oldest_fill_ts_ms")
    retention_rows = report.get("rows")
    retention_reconciled = (
        request_status == "PARTIAL"
        and report.get("retention_cap_reached") is True
        and type(retention_rows) is int
        and retention_rows >= 10_000
        and type(start_ms) is int
        and type(end_ms) is int
        and type(oldest_fill_ms) is int
        and start_ms > 0
        and start_ms <= oldest_fill_ms <= end_ms
    )
    if request_status != "COMPLETE" and not retention_reconciled:
        return None
    if report.get("checkpoint_advance_allowed") is not True:
        return None
    if (
        report.get("request_budget_exhausted") is not False
        or type(report.get("pending_windows")) is not int
        or report.get("pending_windows") != 0
        or type(report.get("invalid_fill_count")) is not int
        or report.get("invalid_fill_count") != 0
        or report.get("failed_windows") != []
        or report.get("cap_blocked_windows") != []
        or (
            retention_reconciled
            and report.get("retention_cap_reached") is not True
        )
        or (
            not retention_reconciled
            and report.get("retention_cap_reached") is not False
        )
    ):
        return None
    if type(end_ms) is not int or end_ms <= 0:
        return None
    unresolved_gaps = report.get("unresolved_gaps")
    if not isinstance(unresolved_gaps, list) or any(
        not isinstance(gap, Mapping) for gap in unresolved_gaps
    ):
        return None
    campaign_id = campaign.get("campaign_id")
    release_tag = report.get("source_release_tag") or campaign.get("release_tag")
    if not isinstance(campaign_id, str) or not isinstance(release_tag, str):
        return None
    return {
        "last_reconciled_end_ms": end_ms,
        "source_campaign_id": campaign_id,
        "source_release_tag": release_tag,
        "unresolved_gaps": [dict(gap) for gap in unresolved_gaps],
    }


def load_history_checkpoints(
    campaign_dir: Path,
    *,
    phase_epoch: int,
    addresses: set[str],
) -> dict[str, dict[str, Any]]:
    """Return only verified, durably published checkpoints for these wallets.

    The campaign's stored unit digest binds its result payload. This makes the
    committed campaign receipt, rather than an unverified local data file, the
    source of each historical cursor.
    """
    wanted = {str(address).lower() for address in addresses}
    wanted = {address for address in wanted if _ADDRESS.fullmatch(address)}
    if type(phase_epoch) is not int or phase_epoch < 1 or not wanted:
        return {}

    latest: dict[str, dict[str, Any]] = {}
    try:
        paths = sorted(Path(campaign_dir).glob("copy-vault-*.json"))
    except OSError:
        return {}
    for path in paths:
        campaign = _read_json(path)
        if campaign is None:
            continue
        if (
            campaign.get("kind") != "copy_vault_collection"
            or campaign.get("creation_phase") != "COLLECT"
            or campaign.get("phase_epoch") != phase_epoch
            or campaign.get("status") != "COMPLETE"
        ):
            continue
        units = campaign.get("completed_units")
        if not isinstance(units, Mapping):
            continue
        for unit in units.values():
            if not isinstance(unit, Mapping):
                continue
            payload = unit.get("result")
            if not isinstance(payload, Mapping) or unit.get("sha256") != _digest(payload):
                continue
            if payload.get("durable_persisted") is not True:
                continue
            release_tag = payload.get("release_tag")
            if not isinstance(release_tag, str) or not release_tag.strip():
                continue
            reports = _history_reports_from_payload(payload)
            if reports is None:
                continue
            campaign_with_release = {**campaign, "release_tag": release_tag}
            for raw_address, raw_report in reports.items():
                address = str(raw_address).lower()
                if address not in wanted or not isinstance(raw_report, Mapping):
                    continue
                checkpoint = _checkpoint_from_report(campaign_with_release, raw_report)
                if checkpoint is None:
                    continue
                checkpoint["source_release_tag"] = release_tag
                prior = latest.get(address)
                if (
                    prior is None
                    or checkpoint["last_reconciled_end_ms"] > prior["last_reconciled_end_ms"]
                    or (
                        checkpoint["last_reconciled_end_ms"] == prior["last_reconciled_end_ms"]
                        and checkpoint["source_campaign_id"] > prior["source_campaign_id"]
                    )
                ):
                    latest[address] = checkpoint
    return latest


def load_release_history_audits(
    campaign_dir: Path,
    *,
    release_tags: set[str],
) -> dict[str, Any]:
    """Match SAFE Copy-Vault releases to committed REST coverage receipts."""
    wanted = {str(tag) for tag in release_tags if str(tag).strip()}
    reports_by_release: dict[str, list[dict[str, Any]]] = {}
    durable_receipt_tags: set[str] = set()
    try:
        paths = sorted(Path(campaign_dir).glob("copy-vault-*.json"))
    except OSError:
        paths = []
    for path in paths:
        if path.is_symlink():
            continue
        campaign = _read_json(path)
        if campaign is None or campaign.get("kind") != "copy_vault_collection":
            continue
        if campaign.get("status") != "COMPLETE":
            continue
        units = campaign.get("completed_units")
        if not isinstance(units, Mapping):
            continue
        for unit in units.values():
            if not isinstance(unit, Mapping):
                continue
            payload = unit.get("result")
            if not isinstance(payload, Mapping) or unit.get("sha256") != _digest(payload):
                continue
            release_tag = payload.get("release_tag")
            if (
                payload.get("durable_persisted") is not True
                or not isinstance(release_tag, str)
                or release_tag not in wanted
            ):
                continue
            durable_receipt_tags.add(release_tag)
            reports = _history_reports_from_payload(payload)
            if not isinstance(reports, Mapping) or not reports:
                continue
            rows = reports_by_release.setdefault(release_tag, [])
            for raw_address, raw_report in reports.items():
                if not isinstance(raw_report, Mapping):
                    continue
                raw_gaps = raw_report.get("unresolved_gaps", [])
                gaps_valid = isinstance(raw_gaps, list) and all(
                    isinstance(gap, Mapping) for gap in raw_gaps
                )
                rows.append({
                    "vault": str(raw_address).lower(),
                    "release_tag": release_tag,
                    "status": str(raw_report.get("status") or "UNAVAILABLE"),
                    "request_audit_status": str(
                        raw_report.get("request_audit_status")
                        or raw_report.get("status")
                        or "UNAVAILABLE"
                    ),
                    "requested_start_ms": raw_report.get("requested_start_ms"),
                    "requested_end_ms": raw_report.get("requested_end_ms"),
                    "rows": raw_report.get("rows"),
                    "unresolved_gaps": [
                        dict(gap)
                        for gap in raw_gaps
                        if isinstance(gap, Mapping)
                    ] if gaps_valid else [{"reason": "INVALID_GAP_RECEIPT"}],
                    "retention_cap_reached": raw_report.get("retention_cap_reached"),
                    "request_budget_exhausted": raw_report.get("request_budget_exhausted"),
                    "pending_windows": raw_report.get("pending_windows"),
                    "invalid_fill_count": raw_report.get("invalid_fill_count"),
                    "failed_windows": raw_report.get("failed_windows"),
                    "cap_blocked_windows": raw_report.get("cap_blocked_windows"),
                    "checkpoint_advance_allowed": raw_report.get(
                        "checkpoint_advance_allowed"
                    ),
                })

    audited_release_tags = set(reports_by_release)
    unknown = sorted(wanted - audited_release_tags)
    missing_receipt_tags = sorted(wanted - durable_receipt_tags)
    receipt_without_audit_tags = sorted(durable_receipt_tags - audited_release_tags)
    reports = [row for tag in sorted(reports_by_release) for row in reports_by_release[tag]]
    partial = [
        row for row in reports
        if row["status"] != "COMPLETE"
        or row["request_audit_status"] != "COMPLETE"
        or bool(row["unresolved_gaps"])
        or row["retention_cap_reached"] is True
        or row["request_budget_exhausted"] is not False
        or row["pending_windows"] != 0
        or row["invalid_fill_count"] != 0
        or row["failed_windows"] != []
        or row["cap_blocked_windows"] != []
        or row["checkpoint_advance_allowed"] is False
    ]
    gaps = [
        {"vault": row["vault"], "release_tag": row["release_tag"], **gap}
        for row in reports
        for gap in row["unresolved_gaps"]
    ]
    return {
        "status": "COMPLETE" if not unknown and not partial else "PARTIAL",
        "expected_release_count": len(wanted),
        "audited_release_count": len(reports_by_release),
        "durable_receipt_release_count": len(durable_receipt_tags),
        "missing_durable_receipt_tags": missing_receipt_tags,
        "receipt_without_backfill_audit_tags": receipt_without_audit_tags,
        "unknown_release_tags": unknown,
        "partial_report_count": len(partial),
        "reports": reports,
        "unresolved_gaps": gaps,
    }
