#!/usr/bin/env python3
"""Small deterministic mutations for resumable campaign result metadata."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _exact_nonnegative_int(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _exact_drop_count(value: Any) -> int | None:
    if isinstance(value, dict):
        counts = [_exact_nonnegative_int(item) for item in value.values()]
        return sum(counts) if all(item is not None for item in counts) else None
    return _exact_nonnegative_int(value)


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
    manifest_rows = manifests if isinstance(manifests, list) else []
    manifest_set_complete = (
        isinstance(manifests, list)
        and _exact_nonnegative_int(manifest.get("shard_count")) == len(manifest_rows)
    )
    trade_families={
        "trades","agg_trades","fills","userfills","user_fills","copy_vault_fills"
    }
    trade_count=0
    trade_shards=0
    trade_shards_exact=0
    record_count=0
    compressed_bytes=0
    manifest_record_count=0
    manifest_l2_frames=0
    manifest_bbo_frames=0
    dataset_ids=set()
    for shard in manifest_rows:
        if not isinstance(shard,dict):
            manifest_set_complete=False
            continue
        dataset_id=shard.get("dataset_id")
        if not isinstance(dataset_id, str) or not dataset_id.strip() or dataset_id in dataset_ids:
            manifest_set_complete=False
        else:
            dataset_ids.add(dataset_id)
        raw_records=shard.get("record_count")
        if raw_records is None:
            raw_records=shard.get("event_count")
        exact_records=_exact_nonnegative_int(raw_records)
        if exact_records is None:
            manifest_set_complete=False
            exact_records=0
        if (
            shard.get("record_count") is not None
            and shard.get("event_count") is not None
            and _exact_nonnegative_int(shard.get("event_count")) != exact_records
        ):
            manifest_set_complete=False
        record_count += exact_records
        manifest_record_count += exact_records
        exact_bytes=_exact_nonnegative_int(shard.get("bytes"))
        if exact_bytes is not None:
            compressed_bytes += exact_bytes
        family=str(shard.get("family") or "").lower()
        if not family:
            manifest_set_complete=False
        if family in {"l2book", "copy_vault_l2", "native_market"}:
            manifest_l2_frames += exact_records
        elif family == "bbo":
            manifest_bbo_frames += exact_records
        if family in trade_families:
            trade_shards += 1
            if shard.get("trade_count_exact") is True:
                trade_shards_exact += 1
                exact_trade_count=_exact_nonnegative_int(shard.get("trade_count"))
                if exact_trade_count is None:
                    manifest_set_complete=False
                else:
                    trade_count += exact_trade_count

    collection_metrics = payload.get("collection_metrics")
    structured_metrics = (
        dict(collection_metrics) if isinstance(collection_metrics, dict) else None
    )
    frame_source = "structured_collection_metrics" if structured_metrics is not None else "stdout_summary"
    candidate_metrics = structured_metrics
    raw_stdout=payload.get("stdout")
    if candidate_metrics is None and isinstance(raw_stdout,str) and raw_stdout.strip():
        try:
            summary=json.loads(raw_stdout)
        except (TypeError,ValueError,json.JSONDecodeError):
            summary=None
        if isinstance(summary,dict):
            candidate_metrics = summary

    accepted_frames = persisted_frames = l2_frames = bbo_frames = queue_drops = None
    frame_metric_reasons = []
    if not manifest_set_complete:
        frame_metric_reasons.append("RUN_MANIFEST_COVERAGE_INCOMPLETE")
    if candidate_metrics is None:
        frame_metric_reasons.append("FRAME_METRIC_SOURCE_MISSING_OR_TRUNCATED")
    else:
        candidate_counts = {
            key: _exact_nonnegative_int(candidate_metrics.get(key))
            for key in (
                "accepted_frames",
                "persisted_frames",
                "l2_frames",
                "bbo_frames",
            )
        }
        candidate_counts["queue_drops"] = _exact_drop_count(
            candidate_metrics.get("queue_drops")
        )
        if candidate_metrics.get("frame_metrics_complete") is not True or any(
            value is None for value in candidate_counts.values()
        ):
            frame_metric_reasons.append("STRUCTURED_FRAME_METRICS_MISSING_OR_INEXACT")
        if candidate_counts["persisted_frames"] != manifest_record_count:
            frame_metric_reasons.append("PERSISTED_FRAME_COUNT_MISMATCH")
        if candidate_counts["l2_frames"] != manifest_l2_frames:
            frame_metric_reasons.append("L2_FRAME_COUNT_MISMATCH")
        if candidate_counts["bbo_frames"] != manifest_bbo_frames:
            frame_metric_reasons.append("BBO_FRAME_COUNT_MISMATCH")
        if not frame_metric_reasons:
            accepted_frames = candidate_counts["accepted_frames"]
            persisted_frames = candidate_counts["persisted_frames"]
            l2_frames = candidate_counts["l2_frames"]
            bbo_frames = candidate_counts["bbo_frames"]
            queue_drops = candidate_counts["queue_drops"]

    frame_metrics_complete = not frame_metric_reasons
    merged_collection_metrics = dict(structured_metrics or {})
    merged_collection_metrics.update({
        "trade_count_observed":trade_count,
        "trade_count_coverage_complete":trade_shards == trade_shards_exact,
        "trade_shard_count":trade_shards,
        "trade_shards_exact":trade_shards_exact,
        "record_count_observed":record_count,
        "accepted_frames":accepted_frames,
        "persisted_frames":persisted_frames,
        "l2_frames":l2_frames,
        "bbo_frames":bbo_frames,
        "queue_drops":queue_drops,
        "frame_metrics_complete":frame_metrics_complete,
        "frame_metrics_provenance": {
            "source": frame_source,
            "basis": (
                structured_metrics.get("basis")
                if structured_metrics is not None
                else "parsed_stdout_summary"
            ),
            "run_manifest_sha256": hashlib.sha256(
                run_manifest_path.read_bytes()
            ).hexdigest(),
            "run_manifest_crosscheck": "PASS" if frame_metrics_complete else "FAIL",
            "incomplete_reasons": frame_metric_reasons,
        },
        "shard_count":int(manifest.get("shard_count") or 0),
        "safe_count":int(manifest.get("safe_count") or 0),
        "partial_count":int(manifest.get("partial_count") or 0),
        "reject_count":int(manifest.get("reject_count") or 0),
        "compressed_bytes":compressed_bytes,
    })
    merged_collection_metrics.setdefault("basis", "published_run_manifest")
    payload.update({
        "release_tag":str(tag),
        "release_repository":str(repository),
        "shard_count":int(manifest.get("shard_count") or 0),
        "safe_count":int(manifest.get("safe_count") or 0),
        "partial_count":int(manifest.get("partial_count") or 0),
        "reject_count":int(manifest.get("reject_count") or 0),
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
