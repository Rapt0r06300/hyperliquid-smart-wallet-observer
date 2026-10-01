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
    payload.update({
        "release_tag":str(tag),
        "release_repository":str(repository),
        "shard_count":int(manifest.get("shard_count") or 0),
        "safe_count":int(manifest.get("safe_count") or 0),
        "partial_count":int(manifest.get("partial_count") or 0),
        "reject_count":int(manifest.get("reject_count") or 0),
        "durable_persisted":True,
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


def mark_durability_failure(result_path: Path) -> dict[str, Any]:
    previous: dict[str,Any]={}
    try:
        previous=_load(result_path)
    except (OSError,ValueError,json.JSONDecodeError):
        previous={}
    payload={
        "status":"FAILED",
        "reason":"durable_publication_failed",
        "failure_category":"INFRASTRUCTURE",
        "previous_status":previous.get("status"),
        "previous_sha256":previous.get("sha256"),
    }
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
        row=mark_durability_failure(Path(args.result))
    print(json.dumps(row,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
