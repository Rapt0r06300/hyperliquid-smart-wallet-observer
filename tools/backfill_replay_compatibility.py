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
from urllib.parse import quote

from manifest_policy import classify_manifest, is_official_historical_archive
from replay_compatibility import VERIFIER_VERSION, inspect_asset

try:
    from tools.backfill_exact_trade_counts import IDENTITY_VERSION, _extract_packed_verified_shard
except ModuleNotFoundError:
    from backfill_exact_trade_counts import IDENTITY_VERSION, _extract_packed_verified_shard

ROOT=Path(__file__).resolve().parents[1]
INDEX_PATH=ROOT/"catalog"/"DATA_INDEX.json"
PATCH_PATH=ROOT/"catalog"/"REPLAY_COMPAT_PATCH.json"
CATALOG_PATH=ROOT/"catalog"/"DATA_CATALOG.json"
REGISTRY_PATH=ROOT/"catalog"/"DATA_QUALITY_REGISTRY.json"
TRADE_COUNT_PATCH_PATH=ROOT/"catalog"/"TRADE_COUNT_PATCH.json"
GLOBAL_UNIQUE_PATCH_PATH=ROOT/"catalog"/"TRADE_UNIQUE_COUNT_PATCH.json"
GLOBAL_IDENTITY_VERSION="native-id-or-venue-family-symbol-time-side-price-size-v3-full-string"

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
        "release_tag": manifest.get("release_tag") or release_map.get("release_tag") or release_map.get("tag"),
        "release_asset": manifest.get("release_asset") or (
            release_map.get("member_name") if release_map.get("storage") == "zip_entry"
            else release_map.get("asset_name")
        ),
        "release_storage": manifest.get("release_storage") or release_map.get("storage"),
        "release_container_asset": manifest.get("release_container_asset") or (
            release_map.get("asset_name") if release_map.get("storage") == "zip_entry" else None
        ),
        "release_member": manifest.get("release_member") or release_map.get("member_name"),
        "release_remote_size": manifest.get("release_remote_size") or release_map.get("remote_size"),
        "release_remote_digest": manifest.get("release_remote_digest") or release_map.get("remote_digest"),
        "sha256": manifest.get("sha256"),
        "bytes": manifest.get("bytes"),
    }
    for key,value in fallback.items():
        if row.get(key) in (None,"") and value not in (None,""):
            row[key]=value


def _load_global_unique_rows(*, root: Path) -> dict[str,Mapping[str,Any]]:
    path=root/"catalog"/"TRADE_UNIQUE_COUNT_PATCH.json"
    if not path.is_file():
        return {}
    try:
        patch=_load_json(path)
    except (OSError,ValueError,json.JSONDecodeError):
        return {}
    if str(patch.get("identity_version") or "")!=GLOBAL_IDENTITY_VERSION:
        return {}
    counts=patch.get("counts")
    if not isinstance(counts,Mapping):
        return {}
    return {
        str(dataset_id): evidence
        for dataset_id,evidence in counts.items()
        if isinstance(evidence,Mapping)
    }


def _global_unique_evidence_valid(
    row: Mapping[str,Any],
    evidence: Mapping[str,Any] | None,
) -> bool:
    if not isinstance(evidence,Mapping) or evidence.get("unique_trade_count_exact") is not True:
        return False
    if row.get("trade_count_exact") is not True:
        return False
    try:
        trade_count=int(row.get("trade_count"))
        scanned=int(evidence.get("trade_count_scanned"))
        unique_count=int(evidence.get("unique_trade_count"))
    except (TypeError,ValueError,OverflowError):
        return False
    return trade_count>=0 and scanned==trade_count and 0<=unique_count<=trade_count


def _candidate(
    row: Mapping[str,Any],
    known: Mapping[str,Any],
    families: set[str],
    unique_rows: Mapping[str,Mapping[str,Any]] | None=None,
) -> bool:
    dataset_id=str(row.get("dataset_id") or "")
    family=str(row.get("family") or "").lower()
    if not dataset_id:
        return False
    if families and family not in families:
        return False

    unique_evidence=(unique_rows or {}).get(dataset_id)
    metadata_repair=bool(
        row.get("replay_compatible") is True
        and str(row.get("quality_status") or "").upper()=="PARTIAL"
        and family in {"trades","agg_trades","fills","userfills","user_fills","copy_vault_fills"}
        and row.get("unique_trade_count_exact") is not True
        and _global_unique_evidence_valid(row,unique_evidence)
    )
    if row.get("replay_compatible") is True and not metadata_repair:
        return False

    prior=known.get(dataset_id)
    if isinstance(prior,Mapping):
        if prior.get("replay_compatible") is True and not metadata_repair:
            return False
        # Failed receipts from older verifier semantics must be retried once.
        # A failure produced by the current verifier is stable and must not loop.
        if (
            prior.get("replay_compatible") is not True
            and str(prior.get("verifier_version") or "")==VERIFIER_VERSION
        ):
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
    if metadata_repair:
        return True
    # Immutable legacy SAFE/PARTIAL shards may predate replay receipts. Running
    # the strict parser can prove deterministic replay without pretending that
    # PARTIAL source reconciliation suddenly became SAFE.
    if status in {"SAFE","PARTIAL"}:
        return True

    # Legacy official archives were historically placed in REJECT/REJECTED
    # because local receive-monotonic timestamps cannot exist in downloaded
    # history. Admit only verified official archives to the strict verifier.
    if status in {"REJECT","REJECTED","PARTIAL"}:
        if manifest and is_official_historical_archive(manifest):
            return True
        # Historical HTTP Copy-Vault state lacks exchange timestamps by API
        # design. Only allow it into the immutable asset verifier; this is NOT
        # a SAFE promotion. Every TickEnvelope must subsequently prove causality.
        expected_sources = {
            "copy_vault_positions": "hyperliquid_public_info",
            "copy_vault_selection": "hyperliquid_public_vaults",
        }
        if (
            family == "cross_venue_capacity_tape"
            and isinstance(manifest, Mapping)
            and manifest.get("source") == "cross_venue_derived_capacity"
            and manifest.get("asset_verified") is True
            and str(manifest.get("sha256") or "").lower() == str(row.get("sha256") or "").lower()
            and str(row.get("release_repository") or "") == "Rapt0r06300/hyperliquid-smart-wallet-observer"
        ):
            provenance = manifest.get("provenance")
            if isinstance(provenance, Mapping) and (
                provenance.get("public_data_only") is True
                and provenance.get("authenticated") is False
                and provenance.get("real_execution") is False
                and provenance.get("transports") == ["derived"]
            ):
                return True
        if (
            isinstance(manifest,Mapping)
            and family in expected_sources
            and manifest.get("source") == expected_sources[family]
            and manifest.get("asset_verified") is True
            and str(manifest.get("sha256") or "").lower() == str(row.get("sha256") or "").lower()
            and str(row.get("release_repository") or "") == "Rapt0r06300/hyperliquid-smart-wallet-observer"
        ):
            provenance = manifest.get("provenance")
            if isinstance(provenance,Mapping):
                transports = provenance.get("transports")
                if transports == ["https"] and provenance.get("authenticated") is False and provenance.get("public_data_only") is True:
                    return True
        return False
    return False


def _download(row: Mapping[str,Any], destination: Path) -> Path:
    """Download immutable release assets with a quota-resilient public fallback."""
    repo=str(row["release_repository"])
    tag=str(row["release_tag"])
    asset=str(row.get("release_container_asset") or row["release_asset"])
    destination.mkdir(parents=True,exist_ok=True)
    path=destination/asset

    first=subprocess.run(
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
    if first.returncode==0 and path.is_file():
        if row.get("release_container_asset"):
            extracted = _extract_packed_verified_shard(row, path, destination)
            path.unlink(missing_ok=True)
            return extracted
        return path

    parts=repo.split("/",1)
    if len(parts)!=2 or not all(parts):
        raise BackfillError("invalid release repository")
    owner,name=parts
    url=(
        "https://github.com/"+quote(owner,safe="")+"/"+quote(name,safe="")
        +"/releases/download/"+quote(tag,safe="")
        +"/"+quote(asset,safe="")
    )
    fallback=subprocess.run(
        [
            "curl","--fail","--location","--silent","--show-error",
            "--retry","4","--retry-all-errors","--retry-delay","2",
            "--connect-timeout","20","--max-time","180",
            "--output",os.fspath(path),url,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if fallback.returncode!=0 or not path.is_file():
        detail=" | ".join(
            value.strip()
            for value in (
                first.stderr or first.stdout or "",
                fallback.stderr or fallback.stdout or "",
            )
            if value and value.strip()
        )
        raise BackfillError(("release download failed: "+detail)[-700:])
    if row.get("release_container_asset"):
        extracted = _extract_packed_verified_shard(row, path, destination)
        path.unlink(missing_ok=True)
        return extracted
    return path


def _verify_asset(path: Path, row: Mapping[str,Any]) -> None:
    expected_size=int(row.get("bytes") or 0)
    expected_sha=str(row.get("sha256") or "").lower()
    if expected_size<=0 or path.stat().st_size!=expected_size:
        raise BackfillError("asset size mismatch")
    actual=_sha256(path)
    if len(expected_sha)!=64 or actual!=expected_sha:
        raise BackfillError("asset sha256 mismatch")


def _restore_exact_trade_count_evidence(manifest: dict[str,Any], *, root: Path) -> bool:
    """Restore SHA-matched exact counts and current global-v3 uniqueness proof."""
    dataset_id=str(manifest.get("dataset_id") or "")
    if not dataset_id:
        return False
    path=root/"catalog"/"TRADE_COUNT_PATCH.json"
    if not path.is_file():
        return False
    try:
        patch=_load_json(path)
    except (OSError,ValueError,json.JSONDecodeError):
        return False
    counts=patch.get("counts")
    if not isinstance(counts,Mapping):
        return False
    evidence=counts.get(dataset_id)
    if not isinstance(evidence,Mapping):
        return False
    expected_sha=str(manifest.get("sha256") or "").lower()
    evidence_sha=str(evidence.get("asset_sha256") or "").lower()
    if len(expected_sha)!=64 or evidence_sha!=expected_sha:
        return False
    if evidence.get("trade_count_exact") is not True:
        return False

    manifest["trade_count"]=evidence.get("trade_count")
    manifest["trade_count_exact"]=True

    global_rows=_load_global_unique_rows(root=root)
    global_evidence=global_rows.get(dataset_id)
    proof_row=dict(manifest)
    proof_row["trade_count"]=evidence.get("trade_count")
    proof_row["trade_count_exact"]=True
    if _global_unique_evidence_valid(proof_row,global_evidence):
        manifest["unique_trade_count"]=int(global_evidence["unique_trade_count"])
        manifest["unique_trade_count_exact"]=True
        manifest["unique_identity_method"]=GLOBAL_IDENTITY_VERSION
    else:
        method=str(evidence.get("unique_identity_method") or "")
        if (
            str(manifest.get("venue") or "").lower()=="bybit"
            and method!=IDENTITY_VERSION
        ):
            manifest["unique_trade_count"]=None
            manifest["unique_trade_count_exact"]=False
        elif evidence.get("unique_trade_count_exact") is True:
            manifest["unique_trade_count"]=evidence.get("unique_trade_count")
            manifest["unique_trade_count_exact"]=True
            manifest["unique_identity_method"]=method

    for key in ("record_count_scanned","asset_sha256"):
        if key in evidence:
            manifest[key]=evidence[key]
    return True


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

    authoritative_count=_restore_exact_trade_count_evidence(manifest,root=root)

    for key in (
        "record_count",
        "invalid_record_count",
        "out_of_order_count",
        "duplicate_count",
        "gap_count",
        "replay_compatible",
        "replay_schema_version",
        "replay_reason",
        "verifier_version",
    ):
        if key in result:
            manifest[key]=result[key]

    # Replay inspection and exact counting are independent proofs. If a
    # SHA-matched exact-count receipt exists, replay can never overwrite it.
    if not authoritative_count:
        if result.get("trade_count_exact") is True:
            manifest["trade_count"]=result.get("trade_count")
            manifest["trade_count_exact"]=True
        elif manifest.get("trade_count_exact") is not True:
            manifest["trade_count"]=result.get("trade_count")
            manifest["trade_count_exact"]=False
    manifest.pop("replay_validation_pending",None)
    manifest.pop("pre_replay_quality_status",None)

    if result.get("cross_venue_receive_clock_verified") is True:
        if (
            result.get("verified_from_release") is not True
            or result.get("asset_sha256") != manifest.get("sha256")
            or manifest.get("source") != "cross_venue_derived_capacity"
            or str(manifest.get("family") or "").lower() != "cross_venue_capacity_tape"
        ):
            raise BackfillError("cross-venue tape lacks immutable Release verification")
        old = dict(manifest.get("integrity") or {})
        manifest["historical_cross_venue_clock_repair"] = {
            "method": "verified_dual_leg_receive_clock_scan_v1",
            "verifier_version": VERIFIER_VERSION,
            "release_asset_sha256": result["asset_sha256"],
            "verified_records": result.get("record_count"),
            "previous_regression_count": old.get("regression_count"),
            "exchange_timestamp_invented": False,
            "parent_l2_shard_verified": False,
            "proof_of_pnl_allowed": False,
        }
        old["regression_count"] = 0
        manifest["integrity"] = old
        provenance = dict(manifest.get("provenance") or {})
        provenance["timestamp_semantics"] = ["receive_observation_time_only"]
        manifest["provenance"] = provenance
        # The verified observation tape is replayable, but its parent L2
        # shards remain unverified and its status cannot be forcibly SAFE.

    if result.get("receive_only_snapshot_verified") is True:
        # No invented exchange time: store the old integrity result for audit
        # and correct only the missing-exchange label after immutable SHA
        # verification and a full envelope-by-envelope receive-clock proof.
        if result.get("verified_from_release") is not True or result.get("asset_sha256") != manifest.get("sha256"):
            raise BackfillError("receive-only snapshot lacks immutable Release verification")
        family=str(manifest.get("family") or "").lower()
        original=manifest.get("integrity")
        original=original if isinstance(original,Mapping) else {}
        if family not in {"copy_vault_positions","copy_vault_selection"}:
            raise BackfillError("invalid receive-only snapshot family")
        manifest["historical_receive_only_repair"] = {
            "method": "immutable_tick_envelope_receive_clock_scan_v1",
            "verifier_version": VERIFIER_VERSION,
            "release_asset_sha256": result["asset_sha256"],
            "verified_records": result.get("record_count"),
            "previous_missing_timestamp_count": original.get("missing_timestamp_count"),
            "exchange_timestamp_invented": False,
        }
        integrity=dict(original)
        integrity["missing_timestamp_count"]=0
        manifest["integrity"]=integrity
        provenance=dict(manifest.get("provenance") or {})
        provenance["timestamp_semantics"]=["receive_observation_time_only"]
        manifest["provenance"]=provenance
        manifest["reconciliation"]={
            "status": "SNAPSHOT_VERIFIED",
            "method": "immutable_read_only_http_observation_sha256_scan",
        }

    if result.get("receive_only_context_verified") is True:
        if (
            result.get("verified_from_release") is not True
            or result.get("asset_sha256") != manifest.get("sha256")
            or str(manifest.get("source") or "") != "hyperliquid_public_ws"
            or str(manifest.get("family") or "").lower() != "activeassetctx"
        ):
            raise BackfillError("receive-only context lacks immutable release proof")
        original=dict(manifest.get("integrity") or {})
        manifest["historical_receive_only_repair"] = {
            "method": "unique_receive_clock_hyperliquid_context_v1",
            "verifier_version": VERIFIER_VERSION,
            "release_asset_sha256": result["asset_sha256"],
            "verified_records": result.get("record_count"),
            "previous_duplicate_count": original.get("duplicate_count"),
            "previous_missing_timestamp_count": original.get("missing_timestamp_count"),
            "exchange_timestamp_invented": False,
        }
        # Repeated values at DISTINCT monotonic receive times are independent
        # observations, not duplicate market trades. Preserve the old count.
        original["duplicate_count"]=0
        original["duplicates_deduped"]=True
        original["missing_timestamp_count"]=0
        manifest["integrity"]=original
        provenance=dict(manifest.get("provenance") or {})
        provenance["timestamp_semantics"]=["receive_observation_time_only"]
        manifest["provenance"]=provenance

    if result.get("derived_capacity_lineage_verified") is True:
        if (
            result.get("verified_from_release") is not True
            or result.get("asset_sha256") != manifest.get("sha256")
            or str(manifest.get("family") or "").lower() != "capacity_tape"
        ):
            raise BackfillError("derived capacity lineage lacks immutable release proof")
        manifest["derived_capacity_lineage_receipt"]={
            "method": "immutable_derived_envelope_l2_hash_consistency_v1",
            "release_asset_sha256": result["asset_sha256"],
            "verified_records": result.get("record_count"),
            "parent_l2_shard_verified": False,
            "proof_of_pnl_allowed": False,
        }

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
        "unique_trade_count":manifest.get("unique_trade_count"),
        "unique_trade_count_exact":manifest.get("unique_trade_count_exact"),
        "unique_identity_method":manifest.get("unique_identity_method"),
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


def _candidate_sort_key(row: Mapping[str, Any]) -> tuple[int, int, int, str]:
    family = str(row.get("family") or "").lower()
    source = str(row.get("source") or "").lower()
    # Verified historical archives can repair otherwise irreplaceable missing
    # trades in bulk. Prioritize them *within their family*, never bypassing
    # strict asset SHA / replay verification or promoting mismatched data.
    archive_priority = 0 if (
        "official_archive" in source
        and str(row.get("release_repository") or "")
            == "Rapt0r06300/hyperliquid-smart-wallet-observer"
    ) else 1
    return (
        _FAMILY_PRIORITY.get(family, 50),
        archive_priority,
        -int(row.get("end_ts_ms") or 0),
        str(row.get("dataset_id") or ""),
    )


def backfill(limit: int, families: set[str]) -> dict[str,Any]:
    index=_load_json(INDEX_PATH)
    rows=index.get("shards")
    if not isinstance(rows,list):
        raise BackfillError("invalid data index")

    patch=_load_patch()
    known=patch.get("results")
    if not isinstance(known,dict):
        raise BackfillError("invalid replay patch results")

    unique_rows=_load_global_unique_rows(root=ROOT)
    candidates=[
        row for row in rows
        if isinstance(row,dict) and _candidate(row,known,families,unique_rows)
    ]
    candidates.sort(key=_candidate_sort_key)
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
                result["verifier_version"]=VERIFIER_VERSION
                before=str(row.get("quality_status") or "")
                _apply_result(row,result,root=ROOT)
                after=str(row.get("quality_status") or "")
                known[dataset_id]=dict(result)
                updated+=1
                replayable+=int(result.get("replay_compatible") is True)
                demoted+=int(before=="SAFE" and after!="SAFE")
            except Exception as exc:
                failed.append({
                    "dataset_id":dataset_id,
                    "error":type(exc).__name__,
                    "detail":str(exc)[-500:],
                })
            finally:
                shutil.rmtree(tmp_root/dataset_id,ignore_errors=True)

    patch["results"]=dict(sorted(known.items()))
    patch["processed_assets"]=len(known)
    remaining=sum(
        1 for row in rows
        if isinstance(row,dict) and _candidate(row,known,families,unique_rows)
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
