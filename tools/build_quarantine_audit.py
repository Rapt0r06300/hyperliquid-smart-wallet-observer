#!/usr/bin/env python3
"""Audit every non-SAFE Dataset V2 shard without changing collection state."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.manifest_policy import classify_manifest, is_official_historical_archive
except ModuleNotFoundError:
    from manifest_policy import classify_manifest, is_official_historical_archive

ROOT = Path(__file__).resolve().parents[1]
QUARANTINE_STATUSES = {"PARTIAL", "QUARANTINE", "QUARANTINED"}
REJECT_STATUSES = {"REJECT", "REJECTED"}
NON_SAFE_STATUSES = QUARANTINE_STATUSES | REJECT_STATUSES | {"STALE"}


def _load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def _count(value: Any) -> int:
    try:
        out = int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, out)


def _reasons(row: Mapping[str, Any], manifest: Mapping[str, Any]) -> list[str]:
    value = row.get("quality_reasons")
    if not isinstance(value, list):
        value = manifest.get("quality_reasons")
    if not isinstance(value, list):
        value = []
    normalized = sorted({str(item).strip() for item in value if str(item).strip()})
    if normalized:
        return normalized
    replay_reason = str(row.get("replay_reason") or manifest.get("replay_reason") or "").strip()
    return [replay_reason] if replay_reason and row.get("replay_compatible") is not True else []


def _is_live_only_historical_reason(reason: str) -> bool:
    text = reason.lower()
    return (
        "missing_monotonic" in text
        or reason == "RECONCILIATION_MATCH_REQUIRED"
    )


def _category(
    stored_status: str,
    current_status: str,
    *,
    historical_archive: bool,
    stored_reasons: list[str],
) -> str:
    live_only = (
        historical_archive
        and current_status == "SAFE"
        and bool(stored_reasons)
        and all(_is_live_only_historical_reason(reason) for reason in stored_reasons)
    )
    if live_only:
        return "HISTORICAL_LIVE_RULE_FALSE_QUARANTINE"
    if current_status == "SAFE":
        return "STALE_CLASSIFICATION_NOW_SAFE"
    if stored_status in REJECT_STATUSES and current_status == "PARTIAL":
        return "OVERSTRICT_REJECT_STILL_PARTIAL"
    if stored_status in QUARANTINE_STATUSES:
        return "PARTIAL_EVIDENCE"
    return "LEGITIMATE_EXCLUSION"


def _add_bucket(
    table: dict[str, dict[str, int]],
    key: str,
    *,
    records: int,
) -> None:
    row = table.setdefault(key, {"shards": 0, "records": 0})
    row["shards"] += 1
    row["records"] += records


def build(root: str | Path = ROOT) -> dict[str, Any]:
    base = Path(root)
    index_path = base / "catalog" / "DATA_INDEX.json"
    metrics_path = base / "catalog" / "DATA_METRICS.json"
    record_patch_path = base / "catalog" / "RECORD_COUNT_PATCH.json"
    index = _load(index_path, {})
    metrics = _load(metrics_path, {})
    record_patch = _load(record_patch_path, {})
    record_rows = record_patch.get("records") if isinstance(record_patch, Mapping) else {}
    if not isinstance(record_rows, Mapping):
        record_rows = {}
    shards = index.get("shards") if isinstance(index, Mapping) else []
    if not isinstance(shards, list):
        raise ValueError("DATA_INDEX shards must be a list")
    # A previous successful audit is not a statement about a newer index.
    # Fail closed if metrics and indexed shard identities are not the same
    # snapshot. The metrics pipeline rebuilds both before this audit is run.
    index_digest = hashlib.sha256(index_path.read_bytes()).hexdigest()
    totals = metrics.get("totals") if isinstance(metrics, Mapping) else None
    if (
        not isinstance(totals, Mapping)
        or metrics.get("schema_version") != "alina.data_metrics.v4"
        or metrics.get("source_index_sha256") != index_digest
        or type(totals.get("TOTAL_SHARDS")) is not int
        or totals["TOTAL_SHARDS"] != len(shards)
    ):
        raise ValueError("QUARANTINE_STALE_METRICS: DATA_METRICS is not SHA-bound to DATA_INDEX")
    seen_dataset_ids: set[str] = set()
    for row in shards:
        if not isinstance(row, Mapping):
            raise ValueError("QUARANTINE_BAD_CATALOG_ROW: shard must be an object")
        identity = str(row.get("dataset_id") or "")
        if not identity or identity in seen_dataset_ids:
            raise ValueError("QUARANTINE_DUPLICATE_IDENTITY: every dataset id must be unique")
        seen_dataset_ids.add(identity)
    actual_safe = sum(str(row.get("quality_status") or "").upper() == "SAFE" for row in shards)
    actual_partial = sum(str(row.get("quality_status") or "").upper() == "PARTIAL" for row in shards)
    actual_reject = sum(str(row.get("quality_status") or "").upper() == "REJECT" for row in shards)
    if (
        actual_safe != totals.get("SAFE_SHARDS")
        or actual_partial != totals.get("PARTIAL_SHARDS")
        or actual_reject != totals.get("REJECTED_SHARDS")
        or actual_safe + actual_partial + actual_reject != len(shards)
    ):
        raise ValueError("QUARANTINE_STATUS_MISMATCH: current shard statuses disagree with metrics")

    by_venue: dict[str, dict[str, int]] = {}
    by_family: dict[str, dict[str, int]] = {}
    by_status: dict[str, dict[str, int]] = {}
    by_category: dict[str, dict[str, int]] = {}
    reason_shards: Counter[str] = Counter()
    reason_records: Counter[str] = Counter()
    current_reason_shards: Counter[str] = Counter()
    current_reason_records: Counter[str] = Counter()
    rows_out: list[dict[str, Any]] = []

    quarantine_records = 0
    rejected_records = 0
    stale_records = 0
    historical_non_safe = 0
    live_only_false = 0
    live_only_false_records = 0
    stale_classification = 0
    potential_false_non_safe = 0
    unreadable_manifests = 0

    for row in shards:
        if not isinstance(row, Mapping):
            continue
        stored_status = str(row.get("quality_status") or "UNKNOWN").upper()
        if stored_status not in NON_SAFE_STATUSES:
            continue

        record_evidence = record_rows.get(str(row.get("dataset_id") or ""))
        if (
            isinstance(record_evidence, Mapping)
            and record_evidence.get("exact") is True
            and len(str(row.get("sha256") or "")) == 64
            and str(record_evidence.get("asset_sha256") or "").lower()
                == str(row.get("sha256") or "").lower()
        ):
            records = _count(record_evidence.get("record_count"))
        else:
            records = _count(row.get("record_count") or row.get("event_count"))
        if stored_status in QUARANTINE_STATUSES:
            quarantine_records += records
        elif stored_status in REJECT_STATUSES:
            rejected_records += records
        elif stored_status == "STALE":
            stale_records += records

        manifest_path = base / str(row.get("manifest_path") or "")
        manifest = _load(manifest_path, {})
        if not isinstance(manifest, Mapping) or not manifest:
            unreadable_manifests += 1
            current_status = "UNAVAILABLE"
            current_reasons = ["MANIFEST_UNREADABLE"]
            historical = False
        else:
            current_status, current_reasons = classify_manifest(manifest)
            historical = is_official_historical_archive(manifest)

        stored_reasons = _reasons(row, manifest if isinstance(manifest, Mapping) else {})
        category = _category(
            stored_status,
            current_status,
            historical_archive=historical,
            stored_reasons=stored_reasons,
        )
        if historical:
            historical_non_safe += 1
        if category == "HISTORICAL_LIVE_RULE_FALSE_QUARANTINE":
            live_only_false += 1
            live_only_false_records += records
        if current_status != stored_status:
            stale_classification += 1
        if current_status == "SAFE":
            potential_false_non_safe += 1

        venue = str(row.get("venue") or "unknown").lower()
        family = str(row.get("family") or "unknown").lower()
        _add_bucket(by_venue, venue, records=records)
        _add_bucket(by_family, family, records=records)
        _add_bucket(by_status, stored_status, records=records)
        _add_bucket(by_category, category, records=records)

        for reason in stored_reasons or ["NO_STORED_REASON"]:
            reason_shards[reason] += 1
            reason_records[reason] += records
        for reason in current_reasons or (["CURRENTLY_SAFE"] if current_status == "SAFE" else ["NO_CURRENT_REASON"]):
            current_reason_shards[reason] += 1
            current_reason_records[reason] += records

        drop_count = _count(manifest.get("collection_queue_drops")) if isinstance(manifest, Mapping) else 0
        integrity = manifest.get("integrity") if isinstance(manifest, Mapping) else {}
        integrity = integrity if isinstance(integrity, Mapping) else {}
        gap_count = _count(integrity.get("gap_count"))
        rows_out.append({
            "collection_queue_drops": drop_count,
            "integrity_gap_count": gap_count,
            "queue_drop_attribution_method": (
                manifest.get("queue_drop_attribution_method")
                if isinstance(manifest, Mapping) else None
            ),
            "dataset_id": row.get("dataset_id"),
            "venue": row.get("venue"),
            "family": row.get("family"),
            "symbol": row.get("symbol"),
            "record_count": records,
            "quality_status": stored_status,
            "current_classification": current_status,
            "category": category,
            "historical_archive": historical,
            "replay_compatible": row.get("replay_compatible") is True,
            "stored_reasons": stored_reasons,
            "current_reasons": list(current_reasons),
            "manifest_path": row.get("manifest_path"),
        })

    metric_totals = metrics.get("totals") if isinstance(metrics, Mapping) else {}
    if not isinstance(metric_totals, Mapping):
        metric_totals = {}
    metric_quarantine_records = _count(metric_totals.get("TOTAL_QUARANTINED_RECORDS"))
    metric_rejected_records = _count(metric_totals.get("TOTAL_REJECTED_RECORDS"))
    if (
        quarantine_records != metric_quarantine_records
        or rejected_records != metric_rejected_records
        or len(rows_out) != actual_partial + actual_reject
    ):
        raise ValueError("QUARANTINE_COUNT_MISMATCH: counts disagree with current metrics")

    body = {
        "schema": "alina.quarantine_audit.v1",
        "source_index_sha256": index_digest,
        "source_metrics_sha256": (
            hashlib.sha256(metrics_path.read_bytes()).hexdigest()
            if metrics_path.is_file()
            else None
        ),
        "source_record_count_patch_sha256": (
            hashlib.sha256(record_patch_path.read_bytes()).hexdigest()
            if record_patch_path.is_file()
            else None
        ),
        "source_shard_count": len(shards),
        "non_safe_shard_count": len(rows_out),
        "quarantined_record_count": quarantine_records,
        "metrics_quarantined_record_count": metric_quarantine_records,
        "quarantine_total_matches_metrics": quarantine_records == metric_quarantine_records,
        "rejected_record_count": rejected_records,
        "stale_record_count": stale_records,
        "historical_non_safe_shard_count": historical_non_safe,
        "historical_live_only_false_reject_count": live_only_false,
        "historical_live_only_false_reject_records": live_only_false_records,
        "stale_classification_count": stale_classification,
        "potential_false_non_safe_count": potential_false_non_safe,
        "unreadable_manifest_count": unreadable_manifests,
        "by_status": dict(sorted(by_status.items())),
        "by_venue": dict(sorted(by_venue.items())),
        "by_family": dict(sorted(by_family.items())),
        "by_category": dict(sorted(by_category.items())),
        "stored_reason_counts": {
            key: {"shards": reason_shards[key], "records": reason_records[key]}
            for key in sorted(reason_shards)
        },
        "current_reason_counts": {
            key: {"shards": current_reason_shards[key], "records": current_reason_records[key]}
            for key in sorted(current_reason_shards)
        },
        "reason_record_counts_overlap": True,
        "non_safe_shards": sorted(
            rows_out,
            key=lambda item: (
                str(item.get("quality_status") or ""),
                str(item.get("venue") or ""),
                str(item.get("family") or ""),
                str(item.get("dataset_id") or ""),
            ),
        ),
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    body["receipt_digest"] = hashlib.sha256(canonical.encode()).hexdigest()
    return body


def compact_root_causes(audit: Mapping[str, Any]) -> dict[str, Any]:
    """Publish compact actionable causes, retaining exhaustive audit separately."""
    by_venue_family: dict[str, dict[str, int]] = {}
    reason_by_venue_family: dict[str, dict[str, int]] = {}
    source_gap_causes: dict[str, dict[str, int]] = {}
    queue_loss_manifest_sum = 0
    for shard in audit.get("non_safe_shards") or []:
        if not isinstance(shard, Mapping):
            continue
        key = f"{shard.get('venue') or 'unknown'}|{shard.get('family') or 'unknown'}"
        records = _count(shard.get("record_count"))
        drops = _count(shard.get("collection_queue_drops"))
        gap_count = _count(shard.get("integrity_gap_count"))
        method = shard.get("queue_drop_attribution_method")
        # A legacy cumulative drop counter was repeated for *each* rotated
        # shard: do not describe this sum as distinct frames lost.
        if drops > 0:
            queue_loss_manifest_sum += drops
            cause = (
                "ATTRIBUTED_INGRESS_LOSS_V1"
                if method == "connection_receive_second_v1"
                else "LEGACY_CUMULATIVE_INGRESS_LOSS"
            )
        elif gap_count > 0:
            cause = "SOURCE_SEQUENCE_OR_OTHER_GAP_NO_QUEUE_LOSS"
        else:
            cause = "EVIDENCE_OR_RECONCILIATION_NOT_GAP"
        _add_bucket(source_gap_causes, f"{key}|{cause}", records=records)
        _add_bucket(by_venue_family, key, records=records)
        for reason in shard.get("current_reasons") or ["NO_CURRENT_REASON"]:
            _add_bucket(reason_by_venue_family, f"{key}|{reason}", records=records)

    def ranked(table: Mapping[str, Mapping[str, Any]], limit: int) -> dict[str, Any]:
        return dict(sorted(
            table.items(),
            key=lambda item: (-_count(item[1].get("shards")), item[0]),
        )[:limit])

    return {
        "schema": "alina.quarantine_root_causes.v1",
        "source_index_sha256": audit.get("source_index_sha256"),
        "source_audit_digest": audit.get("receipt_digest"),
        "source_shards": audit.get("source_shard_count"),
        "non_safe_shards": audit.get("non_safe_shard_count"),
        "unreadable_manifest_count": audit.get("unreadable_manifest_count"),
        "potential_false_non_safe_count": audit.get("potential_false_non_safe_count"),
        "quarantine_total_matches_metrics": audit.get("quarantine_total_matches_metrics"),
        "by_status": audit.get("by_status"),
        "by_category": audit.get("by_category"),
        "by_family": audit.get("by_family"),
        "by_venue": audit.get("by_venue"),
        "current_reasons": ranked(audit.get("current_reason_counts") or {}, 60),
        "stored_reasons": ranked(audit.get("stored_reason_counts") or {}, 60),
        "by_venue_family": ranked(by_venue_family, 100),
        "reason_by_venue_family": ranked(reason_by_venue_family, 120),
        "source_gap_causes": ranked(source_gap_causes, 120),
        "queue_drops_sum_across_non_safe_manifests": queue_loss_manifest_sum,
        "queue_drop_sum_is_not_distinct_frames": True,
        "legacy_cumulative_queue_drops_may_be_repeated_across_rotations": True,
        "record_counts_overlap_reasons": True,
        "scope": "indexed_dataset_only",
        "status": "DIAGNOSIS_ONLY",
        "validation_allowed": False,
        "paper_only": True,
        "real_execution": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--output", default="catalog/QUARANTINE_AUDIT.json")
    args = parser.parse_args()
    body = build(args.root)
    output = Path(args.root) / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    causes = compact_root_causes(body)
    causes_path = output.with_name("QUARANTINE_CAUSES.json")
    causes_path.write_text(
        json.dumps(causes, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "root_causes_output": str(causes_path),
        "top_current_reasons": list(causes["current_reasons"].items())[:12],
    }, sort_keys=True))
    print(json.dumps({
        "output": str(output),
        "quarantined_record_count": body["quarantined_record_count"],
        "non_safe_shard_count": body["non_safe_shard_count"],
        "historical_live_only_false_reject_count": body["historical_live_only_false_reject_count"],
        "potential_false_non_safe_count": body["potential_false_non_safe_count"],
        "quarantine_total_matches_metrics": body["quarantine_total_matches_metrics"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
