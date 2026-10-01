#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from manifest_policy import classify_manifest, load_json, verify_asset

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "catalog" / "DATA_INDEX.json"
REGISTRY_PATH = ROOT / "catalog" / "DATA_QUALITY_REGISTRY.json"

_STAGE_BY_STATUS = {
    "SAFE": "safe",
    "PARTIAL": "quarantine",
    "STALE": "quarantine",
    "REJECT": "rejected",
    "NO_DATA": "incoming",
}


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def promote(manifest_path: str | Path, *, asset_path: str | Path | None = None) -> dict:
    manifest = load_json(manifest_path)
    release = manifest.get("release")
    if isinstance(release, dict):
        manifest.setdefault("release_repository", release.get("repository"))
        manifest.setdefault("release_tag", release.get("tag"))
        manifest.setdefault("release_asset", release.get("asset_name"))
    if asset_path is not None:
        verified, verification = verify_asset(manifest, asset_path)
        manifest["asset_verified"] = verified
        manifest["asset_verification"] = verification

    status, reasons = classify_manifest(manifest)
    manifest["quality_status"] = status
    manifest["quality_reasons"] = reasons
    manifest["validation_allowed"] = status == "SAFE"
    # Dataset quality authorizes validation inputs only; it never proves strategy PnL.
    manifest["proof_of_pnl_allowed"] = False

    dataset_id = str(manifest.get("dataset_id") or "").strip()
    if not dataset_id:
        raise ValueError("dataset_id required")
    destination = ROOT / "datasets" / _STAGE_BY_STATUS[status] / f"{dataset_id}.manifest.json"
    _atomic_json(destination, manifest)

    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    shards = [row for row in (index.get("shards") or []) if row.get("dataset_id") != dataset_id]
    shards.append({
        "dataset_id": dataset_id,
        "family": manifest.get("family"),
        "venue": manifest.get("venue"),
        "symbol": manifest.get("symbol"),
        "start_ts_ms": manifest.get("start_ts_ms"),
        "end_ts_ms": manifest.get("end_ts_ms"),
        "quality_status": status,
        "manifest_path": str(destination.relative_to(ROOT)).replace("\\", "/"),
        "release_repository": manifest.get("release_repository"),
        "release_tag": manifest.get("release_tag"),
        "release_asset": manifest.get("release_asset"),
        "sha256": manifest.get("sha256"),
        "bytes": manifest.get("bytes"),
        "event_count": manifest.get("event_count"),
    })
    shards.sort(key=lambda row: (int(row.get("start_ts_ms") or 0), str(row.get("dataset_id") or "")))
    index["shards"] = shards
    index["active_data_status"] = (
        "SAFE"
        if any(row["quality_status"] == "SAFE" for row in shards)
        else ("PARTIAL" if shards else "NO_DATA")
    )
    _atomic_json(INDEX_PATH, index)

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    registry["active_dataset"] = {
        "status": index["active_data_status"],
        "validation_allowed": index["active_data_status"] == "SAFE",
        "proof_of_pnl_allowed": False,
    }
    _atomic_json(REGISTRY_PATH, registry)
    return {
        "dataset_id": dataset_id,
        "status": status,
        "reasons": reasons,
        "destination": str(destination.relative_to(ROOT)).replace("\\", "/"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Qualify and promote one Alina V2 shard manifest.")
    parser.add_argument("manifest")
    parser.add_argument("--asset")
    args = parser.parse_args()
    print(json.dumps(promote(args.manifest, asset_path=args.asset), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
