#!/usr/bin/env python3
"""One-way migration enforcing SAFE => replay_compatible for legacy Dataset V2 rows."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.partitioned_data_index import read_index
    from tools.index_run_manifest import _publish_canonical_index
    from tools.repair_stale_safe_classifications import _archive_prior_manifest
except ModuleNotFoundError:
    from partitioned_data_index import read_index
    from index_run_manifest import _publish_canonical_index
    from repair_stale_safe_classifications import _archive_prior_manifest

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


def migrate(*, dry_run: bool = False) -> dict[str,int]:
    index=read_index(INDEX)
    rows=index.get("shards")
    if not isinstance(rows,list):
        raise ValueError("invalid DATA_INDEX shards")
    migrated=0
    already_proven=0
    missing_manifest=0
    pending: list[tuple[Path, Path, dict[str, Any]]] = []
    root = ROOT.resolve()

    for row in rows:
        if not isinstance(row,dict) or row.get("quality_status")!="SAFE":
            continue
        if row.get("replay_compatible") is True:
            already_proven+=1
            continue

        manifest_path=ROOT/str(row.get("manifest_path") or "")
        if (manifest_path.is_symlink()
                or not manifest_path.resolve().is_relative_to(root)):
            raise ValueError("REPLAY_MIGRATION_UNSAFE_SOURCE_PATH")
        if not manifest_path.is_file():
            missing_manifest+=1
            continue
        manifest=_load(manifest_path)
        identity=str(row.get("dataset_id") or "")
        digest=str(row.get("sha256") or "").lower()
        if (not identity or manifest.get("dataset_id") != identity
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or str(manifest.get("sha256") or "").lower() != digest):
            raise ValueError("REPLAY_MIGRATION_MANIFEST_IDENTITY_MISMATCH")
        if manifest.get("replay_compatible") is True:
            row["replay_compatible"]=True
            row["replay_schema_version"]=manifest.get("replay_schema_version")
            row["replay_reason"]=manifest.get("replay_reason")
            already_proven+=1
            continue

        dataset_id=identity
        if (dataset_id in (".", "..")
                or not re.fullmatch(r"[A-Za-z0-9._-]{1,200}", dataset_id)):
            raise ValueError("REPLAY_MIGRATION_UNSAFE_DATASET_ID")
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
        if (target.is_symlink() or target.parent.is_symlink()
                or not target.resolve().is_relative_to(root)):
            raise ValueError("REPLAY_MIGRATION_UNSAFE_DESTINATION")
        pending.append((manifest_path,target,manifest))

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
    if missing_manifest:
        raise ValueError(f"REPLAY_MIGRATION_MISSING_MANIFESTS:{missing_manifest}")
    if dry_run:
        return {
            "migrated": 0, "planned_demotions": migrated,
            "already_proven": already_proven, "missing_manifest": 0,
            "paper_only": True, "read_only": True,
        }
    archived: dict[Path, str] = {}
    # Validate all targets before touching the index or original receipts.
    for source,target,updated in pending:
        if target.exists():
            current=_load(target)
            if current != updated:
                raise ValueError("REPLAY_MIGRATION_QUARANTINE_DESTINATION_CONFLICT")
    for source,target,updated in pending:
        _,digest=_archive_prior_manifest(ROOT,source)
        archived[source]=digest
        if source.resolve()!=target.resolve() and not target.exists():
            _write(target,updated)
        elif source.resolve()==target.resolve():
            _write(target,updated)
    _publish_canonical_index(INDEX,index)

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
    for source,target,_updated in pending:
        if source.resolve()==target.resolve() or not source.is_file():
            continue
        digest=archived.get(source)
        archive=ROOT/"datasets"/"quarantine"/"reclassification-history"/f"{digest}.original"
        if (digest is None
                or hashlib.sha256(source.read_bytes()).hexdigest()!=digest
                or archive.is_symlink()
                or hashlib.sha256(archive.read_bytes()).hexdigest()!=digest):
            raise ValueError("REPLAY_MIGRATION_ORIGINAL_ARCHIVE_UNVERIFIED")
        source.unlink()
    return {
        "migrated":migrated,
        "already_proven":already_proven,
        "missing_manifest":missing_manifest,
        "safe_after":safe,
        "partial_after":partial,
    }


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Count repairs without writing or removing any files")
    args=parser.parse_args()
    print(json.dumps(migrate(dry_run=args.dry_run),indent=2,sort_keys=True))
