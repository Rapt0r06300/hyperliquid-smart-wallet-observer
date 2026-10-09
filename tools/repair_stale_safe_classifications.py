#!/usr/bin/env python3
"""Repair stale non-SAFE labels when the current canonical policy now proves SAFE."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.manifest_policy import classify_manifest
    from tools.index_run_manifest import _compact_index_row, _normalize_manifest, _valid_release_locator
except ModuleNotFoundError:
    from manifest_policy import classify_manifest
    from index_run_manifest import _compact_index_row, _normalize_manifest, _valid_release_locator

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = Path("catalog/DATA_INDEX.json")
REGISTRY_PATH = Path("catalog/DATA_QUALITY_REGISTRY.json")
CATALOG_PATH = Path("catalog/DATA_CATALOG.json")
NON_SAFE = {"PARTIAL", "STALE", "REJECT", "REJECTED", "QUARANTINE", "QUARANTINED"}
STAGE_BY_STATUS = {
    "SAFE": "safe",
    "PARTIAL": "quarantine",
    "STALE": "quarantine",
    "REJECT": "rejected",
    "NO_DATA": "incoming",
}

MIRROR_KEYS = (
    "family", "venue", "symbol", "start_ts_ms", "end_ts_ms",
    "collection_run_id", "release_repository", "release_tag", "release_asset",
    "sha256", "bytes", "uncompressed_bytes", "uncompressed_size_exact",
    "event_count", "record_count", "trade_count", "trade_count_exact",
    "unique_trade_count", "unique_trade_count_exact", "unique_identity_method",
    "trade_identity_digests_exact",
    "replay_compatible", "replay_schema_version", "replay_reason",
    "quality_reasons", "source",
)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        (json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")) if path.name == "DATA_INDEX.json" else json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True)) + "\n",
        encoding="utf-8",
    )
    if path.name == "DATA_INDEX.json" and temporary.stat().st_size >= 85 * 1024 * 1024:
        temporary.unlink(missing_ok=True)
        raise ValueError("DATA_INDEX_TOO_LARGE: cannot publish unbounded index")
    os.replace(temporary, path)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def repair(root: str | Path = ROOT) -> dict[str, Any]:
    base = Path(root)
    index_path = base / INDEX_PATH
    registry_path = base / REGISTRY_PATH
    catalog_path = base / CATALOG_PATH
    index = _load(index_path)
    registry = _load(registry_path)
    catalog = _load(catalog_path)

    shards = index.get("shards")
    if not isinstance(shards, list):
        raise ValueError("DATA_INDEX shards must be a list")

    repaired: list[dict[str, Any]] = []
    new_rows: list[dict[str, Any]] = []

    for raw_row in shards:
        if not isinstance(raw_row, Mapping):
            continue
        row = dict(raw_row)
        stored_status = str(row.get("quality_status") or "").upper()
        if stored_status not in NON_SAFE:
            new_rows.append(_compact_index_row(row))
            continue

        manifest_rel = str(row.get("manifest_path") or "").strip()
        manifest_path = base / manifest_rel
        if not manifest_rel or not manifest_path.is_file():
            new_rows.append(_compact_index_row(row))
            continue

        manifest = _normalize_manifest(_load(manifest_path))
        current_status, current_reasons = classify_manifest(manifest)
        if current_status == "SAFE" and not _valid_release_locator(manifest):
            current_status = "PARTIAL"
        # Repair only a proven stale negative label. Never auto-demote or weaken
        # a current exclusion here.
        if current_status != "SAFE":
            new_rows.append(_compact_index_row(row))
            continue

        dataset_id = str(manifest.get("dataset_id") or row.get("dataset_id") or "").strip()
        if not dataset_id:
            raise ValueError("dataset_id required for stale classification repair")

        manifest["quality_status"] = "SAFE"
        manifest["quality_reasons"] = list(current_reasons)
        manifest["validation_allowed"] = True
        manifest["proof_of_pnl_allowed"] = False

        destination = base / "datasets" / "safe" / f"{dataset_id}.manifest.json"
        _atomic_json(destination, manifest)

        merged = dict(row)
        for key in MIRROR_KEYS:
            if key in manifest and manifest.get(key) is not None:
                merged[key] = manifest.get(key)
        merged["dataset_id"] = dataset_id
        merged["quality_status"] = "SAFE"
        merged["quality_reasons"] = []
        merged["manifest_path"] = str(destination.relative_to(base)).replace("\\", "/")
        new_rows.append(_compact_index_row(merged))

        # Only delete the stale manifest pointer after the SAFE copy is durable.
        if manifest_path.resolve() != destination.resolve() and manifest_path.is_file():
            manifest_path.unlink()

        repaired.append({
            "dataset_id": dataset_id,
            "from_status": stored_status,
            "to_status": "SAFE",
            "old_manifest_path": manifest_rel,
            "new_manifest_path": merged["manifest_path"],
            "record_count": int(row.get("record_count") or row.get("event_count") or 0),
        })

    new_rows.sort(
        key=lambda row: (
            int(row.get("start_ts_ms") or 0),
            str(row.get("venue") or ""),
            str(row.get("family") or ""),
            str(row.get("symbol") or ""),
            str(row.get("dataset_id") or ""),
        )
    )
    active = (
        "SAFE"
        if any(row.get("quality_status") == "SAFE" for row in new_rows)
        else ("PARTIAL" if new_rows else "NO_DATA")
    )
    safe_count = sum(row.get("quality_status") == "SAFE" for row in new_rows)
    partial_count = sum(row.get("quality_status") == "PARTIAL" for row in new_rows)
    stale_count = sum(row.get("quality_status") == "STALE" for row in new_rows)
    reject_count = sum(row.get("quality_status") in {"REJECT", "REJECTED"} for row in new_rows)

    index["shards"] = new_rows
    index["active_data_status"] = active
    _atomic_json(index_path, index)

    registry["active_dataset"] = {
        "status": active,
        "validation_allowed": active == "SAFE",
        "proof_of_pnl_allowed": False,
        "indexed_shards": len(new_rows),
        "safe_count": safe_count,
        "partial_count": partial_count,
        "stale_count": stale_count,
        "reject_count": reject_count,
    }
    _atomic_json(registry_path, registry)

    catalog["active_data_status"] = active
    catalog["indexed_shard_count"] = len(new_rows)
    catalog["safe_shard_count"] = safe_count
    catalog["partial_shard_count"] = partial_count
    catalog["stale_shard_count"] = stale_count
    catalog["reject_shard_count"] = reject_count
    _atomic_json(catalog_path, catalog)

    return {
        "repaired_count": len(repaired),
        "repaired_record_count": sum(item["record_count"] for item in repaired),
        "repaired": repaired,
        "indexed_shards": len(new_rows),
        "safe_count": safe_count,
        "partial_count": partial_count,
        "stale_count": stale_count,
        "reject_count": reject_count,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    result = repair(args.root)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
