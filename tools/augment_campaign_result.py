#!/usr/bin/env python3
"""Small deterministic mutations for resumable campaign result metadata."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _exact_nonnegative_int(value: Any) -> int | None:
    if type(value) is not int or value < 0:
        return None
    return value


def _load(path: Path) -> dict[str, Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_result(path: Path, row: dict[str, Any]) -> None:
    payload=row.get("payload")
    if not isinstance(payload,dict):
        raise ValueError("result payload must be an object")
    raw=json.dumps(
        payload,
        sort_keys=True,
        separators=(",",":"),
        ensure_ascii=False,
    ).encode()
    row["sha256"]=hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(row,sort_keys=True)+"\n",encoding="utf-8")


def annotate_collection(
    result_path: Path,
    run_manifest_path: Path,
    *,
    tag: str,
    repository: str,
) -> dict[str, Any]:
    row=_load(result_path)
    manifest=_load(run_manifest_path)
    payload=row.setdefault("payload",{})
    if not isinstance(payload,dict):
        raise ValueError("result payload must be an object")

    manifests=manifest.get("manifests")
    manifest_inventory_complete=isinstance(manifests,list)
    if not isinstance(manifests,list):
        manifests=[]
    trade_families={
        "trades","agg_trades","fills","userfills","user_fills","copy_vault_fills"
    }
    trade_count=0
    trade_shards=0
    trade_shards_exact=0
    record_count=0
    compressed_bytes=0
    for shard in manifests:
        if not isinstance(shard,dict):
            manifest_inventory_complete=False
            continue
        shard_records=shard.get("record_count")
        if shard_records is None:
            shard_records=shard.get("event_count")
        exact_records=_exact_nonnegative_int(shard_records)
        exact_bytes=_exact_nonnegative_int(shard.get("bytes"))
        if exact_records is None or exact_bytes is None:
            manifest_inventory_complete=False
        record_count += exact_records or 0
        compressed_bytes += exact_bytes or 0
        family=str(shard.get("family") or "").lower()
        if not family:
            manifest_inventory_complete=False
        if family in trade_families:
            trade_shards += 1
            exact_trade_count=_exact_nonnegative_int(shard.get("trade_count"))
            if shard.get("trade_count_exact") is True and exact_trade_count is not None:
                trade_shards_exact += 1
                trade_count += exact_trade_count

    declared_shards=_exact_nonnegative_int(manifest.get("shard_count"))
    safe_shards=_exact_nonnegative_int(manifest.get("safe_count"))
    partial_shards=_exact_nonnegative_int(manifest.get("partial_count"))
    rejected_shards=_exact_nonnegative_int(manifest.get("reject_count"))
    category_counts_complete=all(
        value is not None
        for value in (declared_shards,safe_shards,partial_shards,rejected_shards)
    ) and safe_shards + partial_shards + rejected_shards == declared_shards
    manifest_inventory_complete=(
        manifest_inventory_complete
        and len(manifests)==declared_shards
        and category_counts_complete
    )
    trade_count_coverage_complete=(
        manifest_inventory_complete and trade_shards==trade_shards_exact
    )

    collection_metrics = payload.get("collection_metrics")
    merged_collection_metrics = (
        dict(collection_metrics) if isinstance(collection_metrics, dict) else {}
    )
    # stdout is deliberately bounded by the campaign adapter and may be a
    # truncated, non-JSON tail. Frame counters come only from the structured
    # checkpoint; missing counters stay unknown instead of becoming zero.
    merged_collection_metrics.setdefault("frame_metrics_complete", False)
    merged_collection_metrics.update({
        "trade_count_observed":trade_count if trade_count_coverage_complete else None,
        "trade_count_observed_lower_bound":trade_count,
        "trade_count_coverage_complete":trade_count_coverage_complete,
        "trade_shard_count":trade_shards,
        "trade_shards_exact":trade_shards_exact,
        "record_count_observed":record_count if manifest_inventory_complete else None,
        "record_count_manifest_lower_bound":record_count,
        "record_count_coverage_complete":manifest_inventory_complete,
        "manifest_inventory_complete":manifest_inventory_complete,
        "shard_count":declared_shards,
        "safe_count":safe_shards,
        "partial_count":partial_shards,
        "reject_count":rejected_shards,
        "compressed_bytes":compressed_bytes if manifest_inventory_complete else None,
        "compressed_bytes_manifest_lower_bound":compressed_bytes,
        "basis":"published_run_manifest",
    })
    payload.update({
        "release_tag":str(tag),
        "release_repository":str(repository),
        "shard_count":declared_shards,
        "safe_count":safe_shards,
        "partial_count":partial_shards,
        "reject_count":rejected_shards,
        "durable_persisted":True,
        "source_admission":manifest.get("source_admission"),
        "collection_metrics":merged_collection_metrics,
    })
    _write_result(result_path,row)
    return row


def annotate_evidence(
    result_path: Path,
    *,
    tag: str,
    repository: str,
) -> dict[str, Any]:
    row=_load(result_path)
    payload=row.setdefault("payload",{})
    if not isinstance(payload,dict):
        raise ValueError("result payload must be an object")
    payload.update({
        "evidence_release_tag":str(tag),
        "evidence_repository":str(repository),
        "durable_persisted":True,
    })
    _write_result(result_path,row)
    return row


def annotate_rejected_collection(result_path: Path, diagnostic_path: Path) -> dict[str, Any]:
    """Terminate an unusable unit without suggesting its Release exists."""
    row = _load(result_path)
    diagnosis = _load(diagnostic_path)
    count = diagnosis.get("excluded_payload_count")
    if (
        row.get("status") != "COMPLETE"
        or diagnosis.get("schema") != "alina.dataset_publication_skipped.v1"
        or diagnosis.get("status") != "NO_REPLAY_ADMISSIBLE_SHARDS"
        or diagnosis.get("read_only") is not True
        or diagnosis.get("real_execution") is not False
        or type(count) is not int or count < 0
    ):
        raise ValueError("INVALID_ZERO_VIABLE_COLLECTION_RECEIPT")
    payload = row.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("result payload must be an object")
    payload.update({
        "reason": "NO_REPLAY_ADMISSIBLE_SHARDS",
        "excluded_payload_count": count,
        "source_admission": diagnosis.get("source_admission"),
        "durable_persisted": False,
        "replay_eligible": False,
        "release_tag": None,
    })
    row["status"] = "PARTIAL"
    row["progressed"] = False
    _write_result(result_path, row)
    return row


def mark_durability_failure(
    result_path: Path,
    *,
    detail_path: Path | None = None,
) -> dict[str, Any]:
    previous: dict[str,Any]={}
    try:
        previous=_load(result_path)
    except (OSError,ValueError,json.JSONDecodeError):
        previous={}
    detail=""
    if detail_path is not None:
        try:
            detail=" ".join(detail_path.read_text(encoding="utf-8",errors="replace").split())
        except OSError:
            detail=""
        detail=detail[-2000:]
    payload={
        "status":"FAILED",
        "reason":"durable_publication_failed",
        "failure_category":"INFRASTRUCTURE",
        "previous_status":previous.get("status"),
        "previous_sha256":previous.get("sha256"),
    }
    if detail:
        payload["publication_error_detail"]=detail
    row={
        "status":"FAILED",
        "payload":payload,
        "progressed":False,
    }
    _write_result(result_path,row)
    return row


def main(argv: list[str] | None=None) -> int:
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest="command",required=True)

    collection=sub.add_parser("collection")
    collection.add_argument("--result",required=True)
    collection.add_argument("--run-manifest",required=True)
    collection.add_argument("--tag",required=True)
    collection.add_argument("--repository",required=True)

    evidence=sub.add_parser("evidence")
    evidence.add_argument("--result",required=True)
    evidence.add_argument("--tag",required=True)
    evidence.add_argument("--repository",required=True)

    rejected=sub.add_parser("rejected-collection")
    rejected.add_argument("--result",required=True)
    rejected.add_argument("--diagnostic",required=True)

    failure=sub.add_parser("durability-failure")
    failure.add_argument("--result",required=True)
    failure.add_argument("--detail-file")

    args=parser.parse_args(argv)
    if args.command=="collection":
        row=annotate_collection(
            Path(args.result),
            Path(args.run_manifest),
            tag=args.tag,
            repository=args.repository,
        )
    elif args.command=="evidence":
        row=annotate_evidence(
            Path(args.result),
            tag=args.tag,
            repository=args.repository,
        )
    elif args.command=="rejected-collection":
        row=annotate_rejected_collection(Path(args.result),Path(args.diagnostic))
    else:
        row=mark_durability_failure(
            Path(args.result),
            detail_path=Path(args.detail_file) if args.detail_file else None,
        )
    print(json.dumps(row,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
