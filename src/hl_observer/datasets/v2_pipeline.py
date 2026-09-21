"""End-to-end packaging and strict qualification for Alina dataset V2 shards."""
from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.datasets.v2_export import (
    build_manifest_from_tick_shard,
    write_manifest,
)

V2_REPOSITORY = "Rapt0r06300/alina-smartflow-datasets-v2"
V2_SCHEMA = "alina.dataset_bundle.v2"

_WS_TRANSPORTS = {"websocket"}
_SNAPSHOT_CHANNELS = {
    "instrument_metadata",
    "open_interest",
}


def infer_reconciliation_status(manifest: Mapping[str, Any]) -> str:
    """Infer only evidence that can be proven locally from the captured shard."""
    provenance = manifest.get("provenance")
    transports = set()
    if isinstance(provenance, Mapping):
        raw = provenance.get("transports")
        if isinstance(raw, list):
            transports = {str(item).lower() for item in raw if str(item)}

    synchronization = manifest.get("synchronization")
    connection_count = 0
    if isinstance(synchronization, Mapping):
        try:
            connection_count = int(synchronization.get("connection_count") or 0)
        except (TypeError, ValueError, OverflowError):
            connection_count = 0

    integrity = manifest.get("integrity")
    clean = False
    if isinstance(integrity, Mapping):
        clean = all(
            int(integrity.get(key) or 0) == 0
            for key in ("gap_count", "regression_count", "desync_count")
        )

    family = str(manifest.get("family") or "")
    if transports and transports.issubset({"https", "http"}) and family in _SNAPSHOT_CHANNELS:
        return "SNAPSHOT_VERIFIED"
    if transports.intersection(_WS_TRANSPORTS) and connection_count == 1 and clean:
        return "SOURCE_CONTINUITY_VERIFIED"
    return "UNVERIFIED"


def assess_manifest(manifest: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Classify a V2 shard. SAFE is deliberately hard to obtain."""
    reasons: list[str] = []
    severe: list[str] = []

    event_count = _int(manifest.get("event_count"))
    size = _int(manifest.get("bytes"))
    start = _int(manifest.get("start_ts_ms"))
    end = _int(manifest.get("end_ts_ms"))
    digest = str(manifest.get("sha256") or "")
    if event_count is None or event_count <= 0:
        severe.append("NO_EVENTS")
    if size is None or size <= 0:
        severe.append("EMPTY_ASSET")
    if len(digest) != 64:
        severe.append("INVALID_SHA256")
    if start is None or end is None or start <= 0 or end < start:
        reasons.append("INVALID_TIME_BOUNDS")

    integrity = manifest.get("integrity")
    if not isinstance(integrity, Mapping):
        severe.append("MISSING_INTEGRITY")
    else:
        for key, reason in (
            ("gap_count", "SEQUENCE_OR_QUEUE_GAP"),
            ("regression_count", "TIME_OR_SEQUENCE_REGRESSION"),
            ("desync_count", "DESYNC"),
        ):
            if int(integrity.get(key) or 0) > 0:
                severe.append(reason)
        if int(integrity.get("duplicate_count") or 0) > 0:
            reasons.append("DUPLICATES_PRESENT")
        if int(integrity.get("missing_timestamp_count") or 0) > 0:
            reasons.append("MISSING_EXCHANGE_OR_RECEIVE_TIMESTAMP")
        if int(integrity.get("missing_monotonic_count") or 0) > 0:
            reasons.append("MISSING_MONOTONIC_TIMESTAMP")

    provenance = manifest.get("provenance")
    if not isinstance(provenance, Mapping):
        severe.append("MISSING_PROVENANCE")
    else:
        if provenance.get("public_data_only") is not True:
            severe.append("NON_PUBLIC_OR_UNKNOWN_SOURCE")
        if provenance.get("authenticated") is not False:
            reasons.append("AUTHENTICATION_STATE_NOT_EXPLICITLY_FALSE")
        if provenance.get("real_execution") is not False:
            severe.append("REAL_EXECUTION_CONTAMINATION")

    synchronization = manifest.get("synchronization")
    transports: set[str] = set()
    if isinstance(provenance, Mapping):
        raw_transports = provenance.get("transports")
        if isinstance(raw_transports, list):
            transports = {
                str(value).lower() for value in raw_transports if str(value).strip()
            }
    if transports.intersection(_WS_TRANSPORTS):
        if not isinstance(synchronization, Mapping):
            reasons.append("MISSING_SYNCHRONIZATION")
        else:
            connection_count = _int(synchronization.get("connection_count")) or 0
            if connection_count != 1:
                reasons.append("NOT_SINGLE_CONNECTION_EPOCH")

    reconciliation = manifest.get("reconciliation")
    reconciliation_status = ""
    if isinstance(reconciliation, Mapping):
        reconciliation_status = str(reconciliation.get("status") or "").upper()
    allowed_reconciliation = {
        "MATCHED",
        "SOURCE_CONTINUITY_VERIFIED",
        "SNAPSHOT_VERIFIED",
    }
    if reconciliation_status not in allowed_reconciliation:
        reasons.append("RECONCILIATION_NOT_VERIFIED")

    required = {
        str(value)
        for value in (manifest.get("required_channels") or [])
        if str(value).strip()
    }
    observed = {
        str(value)
        for value in (manifest.get("observed_channels") or [])
        if str(value).strip()
    }
    if not required.issubset(observed):
        reasons.append("REQUIRED_CHANNEL_MISSING")

    cost_model = manifest.get("cost_model")
    if isinstance(cost_model, Mapping):
        if cost_model.get("applicable") is True and cost_model.get("ready") is not True:
            reasons.append("COST_MODEL_NOT_READY")

    if manifest.get("asset_verified") is not True:
        reasons.append("REMOTE_ASSET_NOT_VERIFIED")

    if severe:
        return "REJECT", sorted(set(severe + reasons))
    if reasons:
        return "PARTIAL", sorted(set(reasons))
    return "SAFE", []


def finalize_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(manifest)
    if str((result.get("reconciliation") or {}).get("status") or "").upper() in {
        "",
        "UNVERIFIED",
    }:
        result["reconciliation"] = {
            "status": infer_reconciliation_status(result),
        }
    status, reasons = assess_manifest(result)
    result["quality_status"] = status
    result["quality_reasons"] = reasons
    result["validation_allowed"] = status == "SAFE"
    result["proof_of_pnl_allowed"] = status == "SAFE"
    return result


def verify_remote_asset(
    manifest: Mapping[str, Any],
    *,
    repository: str,
    release_tag: str,
    release_id: int,
    asset_id: int,
    asset_name: str,
    remote_size: int,
    remote_digest: str,
) -> dict[str, Any]:
    """Attach GitHub asset evidence only if size and SHA-256 match exactly."""
    expected_size = _int(manifest.get("bytes"))
    expected_sha = str(manifest.get("sha256") or "").lower()
    digest = str(remote_digest or "")
    remote_sha = digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else ""
    verified = (
        expected_size is not None
        and int(remote_size) == expected_size
        and len(expected_sha) == 64
        and remote_sha == expected_sha
    )
    result = dict(manifest)
    result["asset_verified"] = verified
    result["release"] = {
        "repository": str(repository),
        "tag": str(release_tag),
        "release_id": int(release_id),
        "asset_id": int(asset_id),
        "asset_name": str(asset_name),
        "remote_size": int(remote_size),
        "remote_digest": digest,
    }
    return finalize_manifest(result)


def build_bundle(
    shard_root: str | Path,
    output_root: str | Path,
    *,
    collector_version: str,
    cost_model_channels: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Create a publication bundle from immutable partitioned tick shards.

    Assets are hard-linked when possible, avoiding a second copy of large L2 data.
    """
    source_root = Path(shard_root)
    output = Path(output_root)
    assets_dir = output / "assets"
    manifests_dir = output / "manifests"
    assets_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    shard_paths = sorted(source_root.glob("**/shards/*.jsonl.gz"))
    manifests: list[dict[str, Any]] = []
    for shard in shard_paths:
        preliminary = build_manifest_from_tick_shard(
            shard,
            collector_version=collector_version,
            reconciliation_status="UNVERIFIED",
            required_channels=(),
            cost_model_applicable=False,
            cost_model_ready=False,
        )
        family = str(preliminary.get("family") or "")
        if family in set(cost_model_channels):
            preliminary["cost_model"] = {
                "applicable": True,
                # Only explicit execution/cost datasets should opt into this.
                # Raw market-data SAFE status is independent from replay cost models.
                "ready": False,
            }
        preliminary["reconciliation"] = {
            "status": infer_reconciliation_status(preliminary),
        }
        preliminary = finalize_manifest(preliminary)

        dataset_id = str(preliminary["dataset_id"])
        asset_name = f"{dataset_id}.jsonl.gz"
        asset_path = assets_dir / asset_name
        if asset_path.exists():
            asset_path.unlink()
        try:
            os.link(shard, asset_path)
        except OSError:
            shutil.copyfile(shard, asset_path)

        preliminary["release_asset"] = asset_name
        preliminary["local_source_path"] = str(shard)
        preliminary["local_asset_path"] = str(asset_path)
        preliminary = finalize_manifest(preliminary)
        write_manifest(preliminary, manifests_dir / f"{dataset_id}.json")
        manifests.append(preliminary)

    index = {
        "schema": V2_SCHEMA,
        "repository": V2_REPOSITORY,
        "collector_version": str(collector_version),
        "shard_count": len(manifests),
        "safe_count": sum(1 for row in manifests if row["quality_status"] == "SAFE"),
        "partial_count": sum(1 for row in manifests if row["quality_status"] == "PARTIAL"),
        "reject_count": sum(1 for row in manifests if row["quality_status"] == "REJECT"),
        "dataset_ids": [row["dataset_id"] for row in manifests],
        "manifests": [f"manifests/{row['dataset_id']}.json" for row in manifests],
        "assets": [f"assets/{row['release_asset']}" for row in manifests],
        "read_only": True,
        "real_execution": False,
    }
    write_manifest(index, output / "BUNDLE_INDEX.json")
    return index


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = [
    "V2_REPOSITORY",
    "V2_SCHEMA",
    "assess_manifest",
    "build_bundle",
    "finalize_manifest",
    "infer_reconciliation_status",
    "verify_remote_asset",
]
