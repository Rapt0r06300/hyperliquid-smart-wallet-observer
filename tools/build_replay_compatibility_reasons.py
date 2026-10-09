#!/usr/bin/env python3
"""Build deterministic, trade-weighted explanations for replay compatibility gaps."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "catalog" / "DATA_INDEX.json"
OUTPUT = ROOT / "catalog" / "REPLAY_COMPATIBILITY_REASONS.json"
TRADE_FAMILIES = {"trades", "agg_trades", "fills", "userfills", "user_fills", "copy_vault_fills"}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _exact_trade_count(row: Mapping[str, Any]) -> int:
    if str(row.get("family") or "").lower() not in TRADE_FAMILIES:
        return 0
    if row.get("trade_count_exact") is not True:
        return 0
    try:
        value = int(row.get("trade_count") or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, value)


def _blocking_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons = row.get("quality_reasons")
    if not isinstance(reasons, list):
        reasons = None
    if reasons is None:
        path = ROOT / str(row.get("manifest_path") or "")
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            manifest = {}
        candidate = manifest.get("quality_reasons") if isinstance(manifest, Mapping) else None
        reasons = candidate if isinstance(candidate, list) else []
    normalized = sorted({str(x) for x in reasons if str(x)})
    if row.get("replay_compatible") is True:
        return []
    if normalized:
        return normalized
    replay_reason = str(row.get("replay_reason") or "").strip()
    return [replay_reason or "REPLAY_COMPATIBILITY_NOT_PROVEN"]



QUARANTINE_OUTPUT = ROOT / "catalog" / "QUARANTINE_CAUSES.json"


def build_quarantine_report(
    rows: list[Mapping[str, Any]],
    classifications: list[Mapping[str, Any]],
    metrics: Mapping[str, Any],
    source_digest: str,
) -> dict[str, Any]:
    """Rebuild quarantine diagnostics from the same index as verified metrics.

    This describes evidence; it never changes the indexed SAFE decision.
    Unknown or non-exact record quantities must not be presented as complete.
    """
    totals = metrics.get("totals")
    if (
        not isinstance(totals, Mapping)
        or metrics.get("schema_version") != "alina.data_metrics.v4"
        or metrics.get("source_index_sha256") != source_digest
        or type(totals.get("TOTAL_SHARDS")) is not int
        or totals["TOTAL_SHARDS"] != len(rows)
        or len(classifications) != len(rows)
    ):
        raise ValueError("QUARANTINE_STALE_METRICS: index/metrics/classifications mismatch")
    groups: dict[str, dict[str, dict[str, int]]] = {
        "by_status": {}, "by_venue": {}, "by_family": {},
        "by_venue_family": {}, "current_reasons": {},
    }
    missing_records = 0
    non_safe = 0

    def bump(group: str, key: str, records: int) -> None:
        target = groups[group].setdefault(key, {"shards": 0, "records": 0})
        target["shards"] += 1
        target["records"] += records

    seen: set[str] = set()
    for row, classification in zip(rows, classifications):
        dataset_id = str(row.get("dataset_id") or "")
        if not dataset_id or dataset_id in seen or dataset_id != str(classification.get("dataset_id") or ""):
            raise ValueError("QUARANTINE_AMBIGUOUS_IDENTITY: missing or duplicate dataset id")
        seen.add(dataset_id)
        status = str(row.get("quality_status") or "")
        if status not in {"SAFE", "PARTIAL", "REJECT"}:
            raise ValueError(f"QUARANTINE_UNKNOWN_STATUS:{status}")
        if status == "SAFE":
            continue
        non_safe += 1
        count = row.get("record_count")
        if type(count) is not int or count < 0:
            count = row.get("event_count")
        if type(count) is not int or count < 0:
            count = 0
            missing_records += 1
        venue = str(row.get("venue") or "unknown").lower()
        family = str(row.get("family") or "unknown").lower()
        bump("by_status", status, count)
        bump("by_venue", venue, count)
        bump("by_family", family, count)
        bump("by_venue_family", venue + "|" + family, count)
        blockers = classification.get("blocking_reasons")
        reasons = [str(value) for value in blockers] if isinstance(blockers, list) and blockers else [
            str(classification.get("reason_code") or "UNSPECIFIED_QUALITY_DEFECT")
        ]
        for reason in sorted(set(reasons)):
            bump("current_reasons", reason, count)

    if (
        len(seen) != len(rows)
        or groups["by_status"].get("PARTIAL", {}).get("shards", 0) != totals.get("PARTIAL_SHARDS")
        or groups["by_status"].get("REJECT", {}).get("shards", 0) != totals.get("REJECTED_SHARDS")
        or len(rows) - non_safe != totals.get("SAFE_SHARDS")
    ):
        raise ValueError("QUARANTINE_COUNTER_MISMATCH: status counts disagree with current metrics")

    report: dict[str, Any] = {
        "schema": "alina.quarantine_root_causes.v2",
        "scope": "indexed_dataset_only",
        "status": "DIAGNOSIS_ONLY",
        "validation_allowed": False,
        "paper_only": True,
        "real_execution": False,
        "source_index_sha256": source_digest,
        "source_shards": len(rows),
        "non_safe_shards": non_safe,
        "quarantine_total_matches_metrics": True,
        "by_status": groups["by_status"],
        "by_venue": dict(sorted(groups["by_venue"].items())),
        "by_family": dict(sorted(groups["by_family"].items())),
        "by_venue_family": dict(sorted(groups["by_venue_family"].items())),
        "current_reasons": dict(sorted(groups["current_reasons"].items())),
        "record_counts_complete": missing_records == 0,
        "record_count_unavailable_shards": missing_records,
        "record_counts_overlap_reasons": True,
        "source_reason_method": "current_catalog_and_sha_bound_manifest_when_available",
    }
    report["source_audit_digest"] = hashlib.sha256(canonical(report).encode()).hexdigest()
    return report

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(OUTPUT))
    parser.add_argument("--quarantine-output", default=str(QUARANTINE_OUTPUT))
    args = parser.parse_args()

    index = json.loads(INDEX.read_text(encoding="utf-8"))
    rows = index.get("shards") or []
    primary_counts: Counter[str] = Counter()
    blocker_shards: Counter[str] = Counter()
    blocker_trades: Counter[str] = Counter()
    classifications = []
    non_replayable_trades = 0
    replayable_trades = 0

    for row in rows:
        if not isinstance(row, Mapping):
            continue
        status = str(row.get("quality_status") or "UNKNOWN")
        replay = row.get("replay_compatible") is True
        trades = _exact_trade_count(row)
        blockers = _blocking_reasons(row)

        if status == "SAFE" and replay:
            primary = "SAFE_REPLAY_COMPATIBLE"
        elif status != "SAFE" and replay:
            primary = f"REPLAYABLE_BUT_{status}"
        elif blockers:
            primary = blockers[0]
        elif status == "SAFE":
            primary = "REPLAY_COMPATIBILITY_NOT_PROVEN"
        else:
            primary = f"NOT_SAFE_OR_REPLAYABLE:{status}"

        primary_counts[primary] += 1
        if replay:
            replayable_trades += trades
        else:
            non_replayable_trades += trades
            for reason in blockers or [primary]:
                blocker_shards[reason] += 1
                blocker_trades[reason] += trades

        classifications.append({
            "dataset_id": row.get("dataset_id"),
            "venue": row.get("venue"),
            "family": row.get("family"),
            "quality_status": status,
            "replay_compatible": replay,
            "reason_code": primary,
            "blocking_reasons": blockers,
            "trade_count": trades,
            "trade_count_exact": row.get("trade_count_exact") is True,
            "replay_schema_version": row.get("replay_schema_version"),
        })

    body = {
        "schema": "alina.replay_compatibility_reasons.v2",
        "source_index_sha256": hashlib.sha256(INDEX.read_bytes()).hexdigest(),
        "row_count": len(classifications),
        "reason_counts": dict(sorted(primary_counts.items())),
        "blocking_reason_shard_counts": dict(sorted(blocker_shards.items())),
        "blocking_reason_trade_counts": dict(sorted(blocker_trades.items())),
        "blocking_reason_trade_counts_overlap": True,
        "replayable_trade_count_exact": replayable_trades,
        "non_replayable_trade_count_exact": non_replayable_trades,
        "classifications": sorted(classifications, key=lambda x: str(x.get("dataset_id") or "")),
        "safe_not_replayable_count": sum(
            1 for x in classifications
            if x["quality_status"] == "SAFE" and not x["replay_compatible"]
        ),
        "replayable_not_safe_count": sum(
            1 for x in classifications
            if x["quality_status"] != "SAFE" and x["replay_compatible"]
        ),
    }
    body["receipt_digest"] = hashlib.sha256(canonical(body).encode()).hexdigest()
    # Write neither report if the current metrics are stale or statuses conflict.
    metrics_path = ROOT / "catalog" / "DATA_METRICS.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    quarantine = build_quarantine_report(
        rows, classifications, metrics, body["source_index_sha256"]
    )
    Path(args.quarantine_output).write_text(
        json.dumps(quarantine, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    Path(args.output).write_text(
        json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "row_count": body["row_count"],
        "replayable_trade_count_exact": replayable_trades,
        "non_replayable_trade_count_exact": non_replayable_trades,
        "safe_not_replayable_count": body["safe_not_replayable_count"],
        "replayable_not_safe_count": body["replayable_not_safe_count"],
        "receipt_digest": body["receipt_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
