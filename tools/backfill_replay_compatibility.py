#!/usr/bin/env python3
"""Backfill replay compatibility from immutable verified Dataset V2 release assets.

No byte-size estimation and no blind promotion: every processed asset is downloaded,
size/SHA-256 checked, parsed, chronology checked, and only then allowed to remain SAFE
with replay_compatible=true.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Mapping

from manifest_policy import classify_manifest, is_official_historical_archive
from replay_compatibility import inspect_asset

ROOT=Path(__file__).resolve().parents[1]
INDEX_PATH=ROOT/"catalog"/"DATA_INDEX.json"
PATCH_PATH=ROOT/"catalog"/"REPLAY_COMPAT_PATCH.json"
CATALOG_PATH=ROOT/"catalog"/"DATA_CATALOG.json"
REGISTRY_PATH=ROOT/"catalog"/"DATA_QUALITY_REGISTRY.json"

_STAGE_BY_STATUS={
    "SAFE":"safe",
    "PARTIAL":"quarantine",
    "STALE":"quarantine",
    "REJECT":"rejected",
    "NO_DATA":"incoming",
}
_FAMILY_PRIORITY={
    "bbo":0,
    "l2book":1,
    "l2":1,
    "book":1,
    "funding_settlement":2,
    "open_interest":3,
    "instrument_metadata":4,
    "trades":5,
    "agg_trades":5,
    "fills":5,
    "userfills":5,
    "user_fills":5,
    "copy_vault_fills":6,
    "copy_vault_l2":7,
    "copy_vault_positions":8,
    "external_events":9,
}


class BackfillError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda:handle.read(4*1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str,Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):
        raise BackfillError(f"invalid object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str,Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(
        json.dumps(dict(value),indent=2,sort_keys=True)+"\n",
        encoding="utf-8",
    )
    os.replace(tmp,path)


def _load_patch() -> dict[str,Any]:
    if not PATCH_PATH.is_file():
        return {
            "schema":"alina.replay_compat_patch.v1",
            "method":"verified_release_asset_parse_chronology_smoke",
            "results":{},
        }
    value=_load_json(PATCH_PATH)
    value.setdefault("schema","alina.replay_compat_patch.v1")
    value.setdefault("method","verified_release_asset_parse_chronology_smoke")
    value.setdefault("results",{})
    return value


def _manifest_for_row(row: Mapping[str,Any]) -> dict[str,Any] | None:
    manifest_path=str(row.get("manifest_path") or "")
    if not manifest_path:
        return None
    try:
        return _load_json(ROOT/manifest_path)
    except (OSError,ValueError,json.JSONDecodeError):
        return None


def _hydrate_release_fields(row: dict[str,Any], manifest: Mapping[str,Any] | None) -> None:
    """Recover immutable release coordinates from the manifest when an old index row lacks them."""
    if not isinstance(manifest,Mapping):
        return
    release=manifest.get("release")
    release_map=release if isinstance(release,Mapping) else {}
    fallback={
        "release_repository": manifest.get("release_repository") or release_map.get("repository"),
        "release_tag": manifest.get("release_tag") or release_map.get("tag"),
        "release_asset": manifest.get("release_asset") or release_map.get("asset_name"),
        "sha256": manifest.get("sha256"),
        "bytes": manifest.get("bytes"),
    }
    for key,value in fallback.items():
        if row.get(key) in (None,"") and value not in (None,""):
            row[key]=value


def _candidate(row: Mapping[str,Any], known: Mapping[str,Any], families: set[str]) -> bool:
    dataset_id=str(row.get("dataset_id") or "")
    family=str(row.get("family") or "").lower()
    if not dataset_id or dataset_id in known:
        return False
    if families and family not in families:
        return False
    if row.get("replay_compatible") is True:
        return False

    manifest=_manifest_for_row(row)
    if isinstance(row,dict):
        _hydrate_release_fields(row,manifest)

    if not all(
        row.get(key) not in (None,"")
        for key in ("release_repository","release_tag","release_asset","sha256","bytes","manifest_path")
    ):
        return False

    status=str(row.get("quality_status") or "").upper()
    pending=row.get("replay_validation_pending") is True
    if status=="SAFE" or (status=="PARTIAL" and pending):
        return True

    # Legacy official archives were historically placed in REJECT/REJECTED
    # because local receive-monotonic timestamps cannot exist in downloaded
    # history. Admit only verified official archives to the strict verifier.
    if status in {"REJECT","REJECTED","PARTIAL"}:
        return bool(manifest and is_official_historical_archive(manifest))
    return False


def _download(row: Mapping[str,Any], destination: Path) -> Path:
    repo=str(row["release_repository"])
    tag=str(row["release_tag"])
    asset=str(row["release_asset"])
    destination.mkdir(parents=True,exist_ok=True)
    process=subprocess.run(
        [
            "gh","release","download",tag,
            "--repo",repo,
            "--pattern",asset,
            "--dir",os.fspath(destination),
            "--clobber",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode!=0:
        raise BackfillError((process.stderr or process.stdout or "download failed").strip())
    path=destination/asset
    if not path.is_file():
        raise BackfillError("downloaded asset missing")
    return path


def _verify_asset(path: Path, row: Mapping[str,Any]) -> None:
    expected_size=int(row.get("bytes") or 0)
    expected_sha=str(row.get("sha256") or "").lower()
    if expected_size<=0 or path.stat().st_size!=expected_size:
        raise BackfillError("asset size mismatch")
    actual=_sha256(path)
    if len(expected_sha)!=64 or actual!=expected_sha:
        raise BackfillError("asset sha256 mismatch")


def _apply_result(
    row: dict[str,Any],
    result: Mapping[str,Any],
    *,
    root: Path,
) -> None:
    manifest_path=root/str(row["manifest_path"])
    manifest=_load_json(manifest_path)
    if str(manifest.get("dataset_id"))!=str(row.get("dataset_id")):
        raise BackfillError("manifest/index dataset_id mismatch")
    if str(manifest.get("sha256") or "").lower()!=str(row.get("sha256") or "").lower():
        raise BackfillError("manifest/index sha256 mismatch")

    for key in (
        "record_count",
        "trade_count",
        "trade_count_exact",
        "invalid_record_count",
        "out_of_order_count",
        "duplicate_count",
        "gap_count",
        "replay_compatible",
        "replay_schema_version",
        "replay_reason",
    ):
        if key in result:
            manifest[key]=result[key]
    manifest.pop("replay_validation_pending",None)
    manifest.pop("pre_replay_quality_status",None)

    if result.get("replay_compatible") is True and is_official_historical_archive(manifest):
        reconciliation=dict(manifest.get("reconciliation") or {})
        reconciliation.update({
            "status":"SOURCE_ARCHIVE_VERIFIED",
            "method":"release_sha256_size_plus_parse_chronology",
        })
        manifest["reconciliation"]=reconciliation

    status,reasons=classify_manifest(manifest)
    manifest["quality_status"]=status
    manifest["quality_reasons"]=reasons
    manifest["validation_allowed"]=status=="SAFE" and manifest.get("replay_compatible") is True
    manifest["proof_of_pnl_allowed"]=False

    target=root/"datasets"/_STAGE_BY_STATUS[status]/f"{manifest['dataset_id']}.manifest.json"
    _write_json(target,manifest)
    if target.resolve()!=manifest_path.resolve() and manifest_path.exists():
        manifest_path.unlink()

    row.pop("replay_validation_pending",None)
    row.pop("pre_replay_quality_status",None)
    row.update({
        "quality_status":status,
        "manifest_path":str(target.relative_to(root)).replace("\\","/"),
        "record_count":manifest.get("record_count",manifest.get("event_count")),
        "trade_count":manifest.get("trade_count"),
        "trade_count_exact":manifest.get("trade_count_exact"),
        "replay_compatible":manifest.get("replay_compatible"),
        "replay_schema_version":manifest.get("replay_schema_version"),
        "replay_reason":manifest.get("replay_reason"),
    })


def _refresh_catalog(index: dict[str,Any], root: Path) -> None:
    rows=[row for row in (index.get("shards") or []) if isinstance(row,dict)]
    active=(
        "SAFE" if any(row.get("quality_status")=="SAFE" for row in rows)
        else ("PARTIAL" if rows else "NO_DATA")
    )
    index["active_data_status"]=active
    _write_json(root/"catalog"/"DATA_INDEX.json",index)

    catalog=_load_json(root/"catalog"/"DATA_CATALOG.json")
    registry=_load_json(root/"catalog"/"DATA_QUALITY_REGISTRY.json")
    counts={
        status:sum(1 for row in rows if row.get("quality_status")==status)
        for status in ("SAFE","PARTIAL","STALE","REJECT")
    }
    catalog.update({
        "active_data_status":active,
        "indexed_shard_count":len(rows),
        "safe_shard_count":counts["SAFE"],
        "partial_shard_count":counts["PARTIAL"],
        "stale_shard_count":counts["STALE"],
        "reject_shard_count":counts["REJECT"],
    })
    registry["active_dataset"]={
        "status":active,
        "validation_allowed":active=="SAFE",
        "proof_of_pnl_allowed":False,
        "indexed_shards":len(rows),
        "safe_count":counts["SAFE"],
        "partial_count":counts["PARTIAL"],
        "stale_count":counts["STALE"],
        "reject_count":counts["REJECT"],
    }
    _write_json(root/"catalog"/"DATA_CATALOG.json",catalog)
    _write_json(root/"catalog"/"DATA_QUALITY_REGISTRY.json",registry)


def backfill(limit: int, families: set[str]) -> dict[str,Any]:
    index=_load_json(INDEX_PATH)
    rows=index.get("shards")
    if not isinstance(rows,list):
        raise BackfillError("invalid data index")

    patch=_load_patch()
    known=patch.get("results")
    if not isinstance(known,dict):
        raise BackfillError("invalid replay patch results")

    candidates=[
        row for row in rows
        if isinstance(row,dict) and _candidate(row,known,families)
    ]
    candidates.sort(
        key=lambda row:(
            _FAMILY_PRIORITY.get(str(row.get("family") or "").lower(),50),
            -int(row.get("end_ts_ms") or 0),
            str(row.get("dataset_id") or ""),
        )
    )
    candidates=candidates[:max(1,int(limit))]

    updated=0
    replayable=0
    demoted=0
    failed: list[dict[str,str]]=[]
    with tempfile.TemporaryDirectory(prefix="alina-replay-compat-") as tmp:
        tmp_root=Path(tmp)
        for row in candidates:
            dataset_id=str(row["dataset_id"])
            try:
                asset=_download(row,tmp_root/dataset_id)
                _verify_asset(asset,row)
                result=inspect_asset(asset,row)
                result["asset_sha256"]=_sha256(asset)
                result["asset_size"]=asset.stat().st_size
                result["verified_from_release"]=True
                result["method"]="parse_chronology_smoke"
                before=str(row.get("quality_status") or "")
                _apply_result(row,result,root=ROOT)
                after=str(row.get("quality_status") or "")
                known[dataset_id]=dict(result)
                updated+=1
                replayable+=int(result.get("replay_compatible") is True)
                demoted+=int(before=="SAFE" and after!="SAFE")
            except Exception as exc:
                failed.append({"dataset_id":dataset_id,"error":type(exc).__name__})
            finally:
                shutil.rmtree(tmp_root/dataset_id,ignore_errors=True)

    patch["results"]=dict(sorted(known.items()))
    patch["processed_assets"]=len(known)
    remaining=sum(
        1 for row in rows
        if isinstance(row,dict) and _candidate(row,known,families)
    )
    patch["remaining_candidates_for_filter"]=remaining
    _write_json(PATCH_PATH,patch)
    _refresh_catalog(index,ROOT)

    return {
        "attempted":len(candidates),
        "updated":updated,
        "replayable":replayable,
        "demoted":demoted,
        "failed":failed,
        "remaining_candidates_for_filter":remaining,
    }


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--limit",type=int,default=20)
    parser.add_argument(
        "--families",
        default="bbo,l2book,l2,book",
        help="Comma separated family priority filter; empty means all SAFE legacy families.",
    )
    args=parser.parse_args()
    families={x.strip().lower() for x in str(args.families).split(",") if x.strip()}
    try:
        result=backfill(args.limit,families)
    except (BackfillError,OSError,ValueError,json.JSONDecodeError) as exc:
        print(f"REPLAY_COMPAT_BACKFILL_NO_GO:{type(exc).__name__}:{exc}")
        return 2
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
