#!/usr/bin/env python3
"""One-way migration enforcing SAFE => replay_compatible for legacy Dataset V2 rows."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

ROOT=Path(__file__).resolve().parents[1]
INDEX=ROOT/"catalog"/"DATA_INDEX.json"
CATALOG=ROOT/"catalog"/"DATA_CATALOG.json"
REGISTRY=ROOT/"catalog"/"DATA_QUALITY_REGISTRY.json"


def _load(path: Path) -> dict[str,Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):
        raise ValueError(f"invalid JSON object: {path}")
    return value


def _write(path: Path, value: Mapping[str,Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(dict(value),indent=2,sort_keys=True)+"\n",encoding="utf-8")
    os.replace(tmp,path)


def migrate() -> dict[str,int]:
    index=_load(INDEX)
    rows=index.get("shards")
    if not isinstance(rows,list):
        raise ValueError("invalid DATA_INDEX shards")
    migrated=0
    already_proven=0
    missing_manifest=0

    for row in rows:
        if not isinstance(row,dict) or row.get("quality_status")!="SAFE":
            continue
        if row.get("replay_compatible") is True:
            already_proven+=1
            continue

        manifest_path=ROOT/str(row.get("manifest_path") or "")
        if not manifest_path.is_file():
            missing_manifest+=1
            continue
        manifest=_load(manifest_path)
        if manifest.get("replay_compatible") is True:
            row["replay_compatible"]=True
            row["replay_schema_version"]=manifest.get("replay_schema_version")
            row["replay_reason"]=manifest.get("replay_reason")
            already_proven+=1
            continue

        dataset_id=str(row.get("dataset_id") or manifest.get("dataset_id") or "")
        if not dataset_id:
            continue
        manifest["pre_replay_quality_status"]="SAFE"
        manifest["replay_validation_pending"]=True
        manifest["quality_status"]="PARTIAL"
        reasons=[
            str(x)
            for x in (manifest.get("quality_reasons") or [])
            if str(x) and str(x)!="REPLAY_COMPATIBILITY_NOT_PROVEN"
        ]
        reasons.append("REPLAY_COMPATIBILITY_NOT_PROVEN")
        manifest["quality_reasons"]=sorted(set(reasons))
        manifest["validation_allowed"]=False
        manifest["proof_of_pnl_allowed"]=False
        target=ROOT/"datasets"/"quarantine"/f"{dataset_id}.manifest.json"
        _write(target,manifest)
        if target.resolve()!=manifest_path.resolve() and manifest_path.exists():
            manifest_path.unlink()

        row["pre_replay_quality_status"]="SAFE"
        row["replay_validation_pending"]=True
        row["quality_status"]="PARTIAL"
        row["manifest_path"]=str(target.relative_to(ROOT)).replace("\\","/")
        row["replay_compatible"]=False
        row["replay_reason"]="REPLAY_COMPATIBILITY_NOT_PROVEN"
        migrated+=1

    active=(
        "SAFE" if any(isinstance(r,dict) and r.get("quality_status")=="SAFE" for r in rows)
        else ("PARTIAL" if rows else "NO_DATA")
    )
    index["active_data_status"]=active
    _write(INDEX,index)

    safe=sum(1 for r in rows if isinstance(r,dict) and r.get("quality_status")=="SAFE")
    partial=sum(1 for r in rows if isinstance(r,dict) and r.get("quality_status")=="PARTIAL")
    stale=sum(1 for r in rows if isinstance(r,dict) and r.get("quality_status")=="STALE")
    reject=sum(1 for r in rows if isinstance(r,dict) and r.get("quality_status")=="REJECT")

    catalog=_load(CATALOG)
    catalog.update({
        "active_data_status":active,
        "indexed_shard_count":len(rows),
        "safe_shard_count":safe,
        "partial_shard_count":partial,
        "stale_shard_count":stale,
        "reject_shard_count":reject,
    })
    _write(CATALOG,catalog)

    registry=_load(REGISTRY)
    registry["active_dataset"]={
        "status":active,
        "validation_allowed":active=="SAFE",
        "proof_of_pnl_allowed":False,
        "indexed_shards":len(rows),
        "safe_count":safe,
        "partial_count":partial,
        "stale_count":stale,
        "reject_count":reject,
    }
    _write(REGISTRY,registry)
    return {
        "migrated":migrated,
        "already_proven":already_proven,
        "missing_manifest":missing_manifest,
        "safe_after":safe,
        "partial_after":partial,
    }


if __name__=="__main__":
    print(json.dumps(migrate(),indent=2,sort_keys=True))
