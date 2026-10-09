#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from tools.manifest_policy import classify_manifest
except ModuleNotFoundError:
    from manifest_policy import classify_manifest

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "catalog" / "DATA_INDEX.json"
REGISTRY_PATH = ROOT / "catalog" / "DATA_QUALITY_REGISTRY.json"
CATALOG_PATH = ROOT / "catalog" / "DATA_CATALOG.json"
TRADE_COUNT_PATCH_PATH = ROOT / "catalog" / "TRADE_COUNT_PATCH.json"
REPLAY_COMPAT_PATCH_PATH = ROOT / "catalog" / "REPLAY_COMPAT_PATCH.json"
BYBIT_IDENTITY_VERSION = "full_native_or_deterministic_composite_string_v3"

_STAGE_BY_STATUS = {
    "SAFE": "safe",
    "PARTIAL": "quarantine",
    "STALE": "quarantine",
    "REJECT": "rejected",
    "NO_DATA": "incoming",
}


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        (json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")) if path.name == "DATA_INDEX.json" else json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True)) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_replay_patch_results(root: Path) -> dict[str, Mapping[str, Any]]:
    path = root / "catalog" / "REPLAY_COMPAT_PATCH.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    results = value.get("results") if isinstance(value, Mapping) else {}
    if not isinstance(results, Mapping):
        return {}
    return {
        str(key): dict(item)
        for key, item in results.items()
        if isinstance(item, Mapping)
    }


def _load_trade_count_patch_results(root: Path) -> dict[str, Mapping[str, Any]]:
    path = root / "catalog" / "TRADE_COUNT_PATCH.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    results = value.get("counts") if isinstance(value, Mapping) else {}
    if not isinstance(results, Mapping):
        return {}
    return {
        str(key): dict(item)
        for key, item in results.items()
        if isinstance(item, Mapping)
    }


def _apply_trade_count_patch(
    manifest: dict[str, Any],
    patch_results: Mapping[str, Mapping[str, Any]],
) -> None:
    dataset_id = str(manifest.get("dataset_id") or "")
    patch = patch_results.get(dataset_id)
    if not isinstance(patch, Mapping):
        return
    expected_sha = str(manifest.get("sha256") or "").lower()
    patched_sha = str(patch.get("asset_sha256") or "").lower()
    if len(expected_sha) != 64 or patched_sha != expected_sha:
        return
    if patch.get("trade_count_exact") is True:
        manifest["trade_count"] = patch.get("trade_count")
        manifest["trade_count_exact"] = True
    method = str(patch.get("unique_identity_method") or "")
    if (
        str(manifest.get("venue") or "").lower() == "bybit"
        and method != BYBIT_IDENTITY_VERSION
    ):
        manifest["unique_trade_count"] = None
        manifest["unique_trade_count_exact"] = False
    elif patch.get("unique_trade_count_exact") is True:
        manifest["unique_trade_count"] = patch.get("unique_trade_count")
        manifest["unique_trade_count_exact"] = True
    if method:
        manifest["unique_identity_method"] = method


def _apply_replay_patch(
    manifest: dict[str, Any],
    patch_results: Mapping[str, Mapping[str, Any]],
) -> None:
    dataset_id = str(manifest.get("dataset_id") or "")
    patch = patch_results.get(dataset_id)
    if not isinstance(patch, Mapping):
        return
    expected_sha = str(manifest.get("sha256") or "").lower()
    patched_sha = str(patch.get("asset_sha256") or "").lower()
    if len(expected_sha) != 64 or patched_sha != expected_sha:
        return
    for key in (
        "record_count",
        "invalid_record_count",
        "out_of_order_count",
        "duplicate_count",
        "gap_count",
        "replay_compatible",
        "replay_schema_version",
        "replay_reason",
    ):
        if key in patch:
            manifest[key] = patch[key]


def _normalize_manifest(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize immutable Release locators, including packed ZIP shards."""
    manifest = dict(raw)
    release = manifest.get("release")
    if isinstance(release, Mapping):
        # Current compacted publisher uses release.release_tag; old direct
        # publisher uses release.tag. Missing this alias previously put tens
        # of thousands of apparently SAFE shards into an unrecoverable index.
        for key, value in (
            ("release_repository", release.get("repository")),
            ("release_tag", release.get("release_tag") or release.get("tag")),
            ("release_id", release.get("release_id")),
            ("release_asset_id", release.get("asset_id")),
            ("release_remote_size", release.get("remote_size")),
            ("release_remote_digest", release.get("remote_digest")),
        ):
            if manifest.get(key) in (None, "") and value not in (None, ""):
                manifest[key] = value

        storage = str(release.get("storage") or "")
        if storage == "zip_entry":
            outer = str(release.get("asset_name") or "")
            member = str(release.get("member_name") or "")
            manifest["release_storage"] = "zip_entry"
            manifest["release_container_asset"] = outer
            manifest["release_member"] = member
            # Keep release_asset as the logical gzip shard name. The physical
            # GitHub downloadable asset is the outer ZIP, pinned separately.
            if manifest.get("release_asset") in (None, ""):
                manifest["release_asset"] = member
        elif manifest.get("release_asset") in (None, ""):
            manifest["release_asset"] = release.get("asset_name")
    return manifest


def _valid_release_locator(manifest: Mapping[str, Any]) -> bool:
    import re
    if (
        manifest.get("release_repository") != "Rapt0r06300/hyperliquid-smart-wallet-observer"
        or not str(manifest.get("release_tag") or "")
        or not str(manifest.get("release_asset") or "")
    ):
        return False
    release = manifest.get("release")
    if isinstance(release, Mapping) and release.get("storage") == "zip_entry":
        digest = str(manifest.get("release_remote_digest") or "")
        member = str(manifest.get("release_member") or "")
        return bool(
            str(manifest.get("release_container_asset") or "").endswith(".zip")
            and member == str(manifest.get("release_asset") or "")
            and member.endswith(".jsonl.gz")
            and "/" not in member and "\\" not in member and ".." not in member
            and re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest)
            and type(manifest.get("release_remote_size")) is int
            and manifest["release_remote_size"] > 0
        )
    return True


def _compact_index_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the selector and metric scalar fields, not repeated evidence.

    Full quality reasons and full trade identities are in the individually
    indexed immutable shard manifests. This does not change eligibility.
    """
    return {
        key: value for key, value in row.items()
        if value is not None
        and key not in {"trade_identity_digests", "quality_reasons"}
    }


def _index_row(manifest: Mapping[str, Any], manifest_path: Path, root: Path) -> dict[str, Any]:
    row = {
        "dataset_id": manifest.get("dataset_id"),
        "family": manifest.get("family"),
        "venue": manifest.get("venue"),
        "symbol": manifest.get("symbol"),
        "start_ts_ms": manifest.get("start_ts_ms"),
        "end_ts_ms": manifest.get("end_ts_ms"),
        "quality_status": manifest.get("quality_status"),
        "collection_run_id": manifest.get("collection_run_id"),
        "manifest_path": str(manifest_path.relative_to(root)).replace("\\", "/"),
        "release_repository": manifest.get("release_repository"),
        "release_tag": manifest.get("release_tag"),
        "release_asset": manifest.get("release_asset"),
        "release_container_asset": manifest.get("release_container_asset"),
        "release_member": manifest.get("release_member"),
        "release_storage": manifest.get("release_storage"),
        "release_remote_size": manifest.get("release_remote_size"),
        "release_remote_digest": manifest.get("release_remote_digest"),
        "sha256": manifest.get("sha256"),
        "bytes": manifest.get("bytes"),
        "uncompressed_bytes": manifest.get("uncompressed_bytes"),
        "uncompressed_size_exact": manifest.get("uncompressed_size_exact"),
        "event_count": manifest.get("event_count"),
        "record_count": manifest.get("record_count", manifest.get("event_count")),
        "trade_count": manifest.get("trade_count"),
        "trade_count_exact": manifest.get("trade_count_exact"),
        "unique_trade_count": manifest.get("unique_trade_count"),
        "unique_trade_count_exact": manifest.get("unique_trade_count_exact"),
        "unique_identity_method": manifest.get("unique_identity_method"),
        # Large identity arrays remain in the per-shard manifest, never duplicated in the global index.
        "trade_identity_digests_exact": manifest.get("trade_identity_digests_exact"),
        "replay_compatible": manifest.get("replay_compatible"),
        "replay_schema_version": manifest.get("replay_schema_version"),
        "replay_reason": manifest.get("replay_reason"),
        "quality_reasons": manifest.get("quality_reasons"),
        "gap_count": (manifest.get("integrity") or {}).get("gap_count"),
        "duplicate_count": (manifest.get("integrity") or {}).get("duplicate_count"),
        "source": manifest.get("source"),
    }
    patch_path = root / "catalog" / "TRADE_COUNT_PATCH.json"
    if patch_path.is_file():
        try:
            patch_doc = json.loads(patch_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            patch_doc = {}
        counts = patch_doc.get("counts") if isinstance(patch_doc, Mapping) else {}
        patched = counts.get(str(manifest.get("dataset_id") or "")) if isinstance(counts, Mapping) else None
        if isinstance(patched, Mapping):
            expected_sha = str(manifest.get("sha256") or "").lower()
            patched_sha = str(patched.get("asset_sha256") or "").lower()
            if len(expected_sha) == 64 and patched_sha == expected_sha:
                if patched.get("trade_count_exact") is True:
                    row["trade_count"] = patched.get("trade_count")
                    row["trade_count_exact"] = True
                method = str(patched.get("unique_identity_method") or "")
                if (
                    str(manifest.get("venue") or "").lower() == "bybit"
                    and method != BYBIT_IDENTITY_VERSION
                ):
                    row["unique_trade_count"] = None
                    row["unique_trade_count_exact"] = False
                elif patched.get("unique_trade_count_exact") is True:
                    row["unique_trade_count"] = patched.get("unique_trade_count")
                    row["unique_trade_count_exact"] = True
                if method:
                    row["unique_identity_method"] = method

    unique_patch_path = root / "catalog" / "TRADE_UNIQUE_COUNT_PATCH.json"
    if unique_patch_path.is_file():
        try:
            unique_doc = json.loads(unique_patch_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            unique_doc = {}
        unique_counts = (
            unique_doc.get("counts") if isinstance(unique_doc, Mapping) else {}
        )
        unique_row = (
            unique_counts.get(str(manifest.get("dataset_id") or ""))
            if isinstance(unique_counts, Mapping)
            else None
        )
        if isinstance(unique_row, Mapping):
            row["unique_trade_count"] = unique_row.get("unique_trade_count")
            row["unique_trade_count_exact"] = (
                unique_row.get("unique_trade_count_exact") is True
            )

    integration = manifest.get("event_intelligence")
    if isinstance(integration, Mapping):
        row.update(
            {
                "event_intelligence_idea_count": integration.get("idea_count"),
                "event_intelligence_coverage_sha256": integration.get(
                    "coverage_sha256"
                ),
                "linked_strategy_families": integration.get(
                    "linked_strategy_families"
                ),
            }
        )
    return _compact_index_row(row)


def index_run_manifests(
    run_manifest_paths: Iterable[str | Path],
    *,
    root: str | Path = ROOT,
) -> dict[str, Any]:
    base = Path(root)
    index_path = base / "catalog" / "DATA_INDEX.json"
    registry_path = base / "catalog" / "DATA_QUALITY_REGISTRY.json"
    catalog_path = base / "catalog" / "DATA_CATALOG.json"

    index = json.loads(index_path.read_text(encoding="utf-8"))
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    replay_patch_results = _load_replay_patch_results(base)
    trade_count_patch_results = _load_trade_count_patch_results(base)
    rows_by_id = {
        str(row.get("dataset_id")): dict(row)
        for row in (index.get("shards") or [])
        if isinstance(row, Mapping) and row.get("dataset_id")
    }
    # Also compact PREEXISTING rows: old DATA_INDEX repeated the full trade
    # digest vectors, already ~77 MiB for only 11k rows. Immutable manifests
    # retain the original vectors for SHA-bound aggregate proof.
    rows_by_id = {
        key: _compact_index_row(old_row)
        for key, old_row in rows_by_id.items()
    }

    imported = 0
    statuses: dict[str, int] = {}
    for run_path in run_manifest_paths:
        payload = json.loads(Path(run_path).read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError(f"invalid run manifest: {run_path}")
        if payload.get("schema") != "alina.dataset_run_manifest.v2":
            raise ValueError(f"unexpected run manifest schema: {run_path}")
        repository = str(payload.get("repository") or "")
        if repository != "Rapt0r06300/hyperliquid-smart-wallet-observer":
            raise ValueError(f"foreign dataset repository refused: {repository}")

        manifests = payload.get("manifests")
        if not isinstance(manifests, list):
            raise ValueError(f"run manifest has no manifests array: {run_path}")

        for raw in manifests:
            if not isinstance(raw, Mapping):
                continue
            manifest = _normalize_manifest(raw)
            dataset_id = str(manifest.get("dataset_id") or "").strip()
            if not dataset_id:
                raise ValueError("dataset_id required")
            _apply_replay_patch(manifest, replay_patch_results)
            _apply_trade_count_patch(manifest, trade_count_patch_results)
            status, reasons = classify_manifest(manifest)
            if status == "SAFE" and not _valid_release_locator(manifest):
                status = "PARTIAL"
                reasons = list(dict.fromkeys([*reasons, "RELEASE_LOCATOR_UNPROVEN"]))
            if status == "SAFE" and manifest.get("replay_compatible") is not True:
                status = "PARTIAL"
                reasons = list(dict.fromkeys([*reasons, "REPLAY_COMPATIBILITY_NOT_PROVEN"]))
            manifest["quality_status"] = status
            manifest["quality_reasons"] = reasons
            manifest["validation_allowed"] = status == "SAFE" and manifest.get("replay_compatible") is True
            # A SAFE shard may be used by validation, but dataset quality alone
            # never proves that any strategy has positive PnL.
            manifest["proof_of_pnl_allowed"] = False

            for stage in set(_STAGE_BY_STATUS.values()):
                stale = base / "datasets" / stage / f"{dataset_id}.manifest.json"
                if stale.exists():
                    stale.unlink()
            destination = (
                base
                / "datasets"
                / _STAGE_BY_STATUS[status]
                / f"{dataset_id}.manifest.json"
            )
            _atomic_json(destination, manifest)
            rows_by_id[dataset_id] = _index_row(manifest, destination, base)
            statuses[status] = statuses.get(status, 0) + 1
            imported += 1

    shards = sorted(
        rows_by_id.values(),
        key=lambda row: (
            int(row.get("start_ts_ms") or 0),
            str(row.get("venue") or ""),
            str(row.get("family") or ""),
            str(row.get("symbol") or ""),
            str(row.get("dataset_id") or ""),
        ),
    )
    active = (
        "SAFE"
        if any(row.get("quality_status") == "SAFE" for row in shards)
        else ("PARTIAL" if shards else "NO_DATA")
    )
    index["shards"] = shards
    index["active_data_status"] = active
    # Fail before attempting a GitHub push past its 100 MiB blob limit.
    _atomic_json(index_path, index)
    if index_path.stat().st_size >= 85 * 1024 * 1024:
        raise ValueError("DATA_INDEX_TOO_LARGE: shard the catalogue before publication; no SAFE evidence dropped")

    safe_count = sum(1 for row in shards if row.get("quality_status") == "SAFE")
    partial_count = sum(1 for row in shards if row.get("quality_status") == "PARTIAL")
    stale_count = sum(1 for row in shards if row.get("quality_status") == "STALE")
    reject_count = sum(1 for row in shards if row.get("quality_status") == "REJECT")

    registry["active_dataset"] = {
        "status": active,
        "validation_allowed": active == "SAFE",
        # Dataset quality can authorize validation, never prove strategy PnL.
        "proof_of_pnl_allowed": False,
        "indexed_shards": len(shards),
        "safe_count": safe_count,
        "partial_count": partial_count,
        "stale_count": stale_count,
        "reject_count": reject_count,
    }
    _atomic_json(registry_path, registry)

    catalog["active_data_status"] = active
    catalog["indexed_shard_count"] = len(shards)
    catalog["safe_shard_count"] = safe_count
    catalog["partial_shard_count"] = partial_count
    catalog["stale_shard_count"] = stale_count
    catalog["reject_shard_count"] = reject_count
    _atomic_json(catalog_path, catalog)
    return {
        "imported_manifests": imported,
        "indexed_shards": len(shards),
        "active_data_status": active,
        "statuses": statuses,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Index verified dataset V2 RUN_MANIFEST release evidence."
    )
    parser.add_argument("run_manifests", nargs="+")
    args = parser.parse_args()
    result = index_run_manifests(args.run_manifests)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())