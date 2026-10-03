#!/usr/bin/env python3
"""Small deterministic mutations for resumable campaign result metadata."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


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
            continue
        record_count += int(shard.get("record_count") or shard.get("event_count") or 0)
        compressed_bytes += int(shard.get("bytes") or 0)
        family=str(shard.get("family") or "").lower()
        if family in trade_families:
            trade_shards += 1
            if shard.get("trade_count_exact") is True:
                trade_shards_exact += 1
                trade_count += int(shard.get("trade_count") or 0)

    accepted_frames=persisted_frames=l2_frames=queue_drops=0
    frame_metrics_complete=False
    raw_stdout=payload.get("stdout")
    if isinstance(raw_stdout,str) and raw_stdout.strip():
        try:
            summary=json.loads(raw_stdout)
        except (TypeError,ValueError,json.JSONDecodeError):
            summary=None
        if isinstance(summary,dict):
            accepted_frames=int(summary.get("accepted_frames") or 0)
            persisted_frames=int(summary.get("persisted_frames") or 0)
            l2_frames=int(summary.get("l2_frames") or 0)
            drops=summary.get("queue_drops")
            if isinstance(drops,dict):
                queue_drops=sum(int(v or 0) for v in drops.values())
            else:
                queue_drops=int(drops or 0)
            frame_metrics_complete=True

    payload.update({
        "release_tag":str(tag),
        "release_repository":str(repository),
        "shard_count":int(manifest.get("shard_count") or 0),
        "safe_count":int(manifest.get("safe_count") or 0),
        "partial_count":int(manifest.get("partial_count") or 0),
        "reject_count":int(manifest.get("reject_count") or 0),
        "durable_persisted":True,
        "collection_metrics":{
            "trade_count_observed":trade_count,
            "trade_count_coverage_complete":trade_shards == trade_shards_exact,
            "trade_shard_count":trade_shards,
            "trade_shards_exact":trade_shards_exact,
            "record_count_observed":record_count,
            "accepted_frames":accepted_frames,
            "persisted_frames":persisted_frames,
            "l2_frames":l2_frames,
            "queue_drops":queue_drops,
            "frame_metrics_complete":frame_metrics_complete,
            "shard_count":int(manifest.get("shard_count") or 0),
            "safe_count":int(manifest.get("safe_count") or 0),
            "partial_count":int(manifest.get("partial_count") or 0),
            "reject_count":int(manifest.get("reject_count") or 0),
            "compressed_bytes":compressed_bytes,
            "basis":"published_run_manifest",
        },
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
    else:
        row=mark_durability_failure(
            Path(args.result),
            detail_path=Path(args.detail_file) if args.detail_file else None,
        )
    print(json.dumps(row,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
