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
    index = _load(index_path, {})
    metrics = _load(metrics_path, {})
    shards = index.get("shards") if isinstance(index, Mapping) else []
    if not isinstance(shards, list):
        raise ValueError("DATA_INDEX shards must be a list")

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

        rows_out.append({
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

    body = {
        "schema": "alina.quarantine_audit.v1",
        "source_index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "source_metrics_sha256": (
            hashlib.sha256(metrics_path.read_bytes()).hexdigest()
            if metrics_path.is_file()
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
