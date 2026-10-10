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
CANONICAL_DATA_REPOSITORY = "Rapt0r06300/hyperliquid-smart-wallet-observer"


def hydrate_default_release_repository(index: Mapping[str, Any]) -> list[dict[str, Any]]:
    """In-memory release locator expansion; never mutate the compact index on disk."""
    raw = index.get("shards")
    if not isinstance(raw, list):
        raise ValueError("DATA_INDEX shards must be a list")
    default = index.get("release_repository_default")
    if default not in (None, CANONICAL_DATA_REPOSITORY):
        raise ValueError("foreign release_repository_default forbidden")
    aliases = index.get("run_manifest_release_tags_by_release") or {}
    if not isinstance(aliases, Mapping) or any(
        not isinstance(k, str) or not k or not isinstance(v, str) or not v
        for k, v in aliases.items()
    ):
        raise ValueError("invalid canonical RUN_MANIFEST tag mapping")
    expanded = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("invalid shard entry")
        row = dict(item)
        if "release_repository" not in row and default == CANONICAL_DATA_REPOSITORY:
            row["release_repository"] = CANONICAL_DATA_REPOSITORY
        canonical = aliases.get(str(row.get("release_tag") or ""))
        if canonical is not None:
            existing = row.get("run_manifest_release_tag")
            if existing not in (None, canonical):
                raise ValueError("conflicting canonical RUN_MANIFEST tag mapping")
            row["run_manifest_release_tag"] = canonical
        expanded.append(row)
    return expanded


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
    if path.name == "DATA_INDEX.json" and temporary.stat().st_size >= 85 * 1024 * 1024:
        temporary.unlink(missing_ok=True)
        raise ValueError("DATA_INDEX_TOO_LARGE: index mutation not published")
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


def _load_global_unique_count_patch_results(root: Path) -> dict[str, Mapping[str, Any]]:
    path = root / "catalog" / "TRADE_UNIQUE_COUNT_PATCH.json"
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    counts = doc.get("counts") if isinstance(doc, Mapping) else {}
    if not isinstance(counts, Mapping):
        return {}
    return {
        str(dataset_id): dict(row)
        for dataset_id, row in counts.items()
        if isinstance(row, Mapping)
    }



def _load_size_proofs(root: Path) -> dict[str, Mapping[str, Any]]:
    path = root / "catalog" / "UNCOMPRESSED_SIZE_PATCH.json"
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entries = doc.get("sizes") if isinstance(doc, Mapping) else None
    return dict(entries) if isinstance(entries, Mapping) else {}


def _size_proof_matches(
    row: Mapping[str, Any], proofs: Mapping[str, Mapping[str, Any]],
) -> bool:
    sha = str(row.get("sha256") or "").lower()
    proof = proofs.get(str(row.get("dataset_id") or ""))
    return bool(
        isinstance(proof, Mapping)
        and len(sha) == 64
        and str(proof.get("asset_sha256") or "").lower() == sha
        and row.get("uncompressed_size_exact") is True
        and type(row.get("uncompressed_bytes")) is int
        and type(proof.get("uncompressed_bytes")) is int
        and proof["uncompressed_bytes"] == row["uncompressed_bytes"]
        and row["uncompressed_bytes"] >= 0
    )


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


def _has_sha_bound_receipt(root: Path, row: Mapping[str, Any]) -> bool:
    """Drop duplicate index diagnostics only when the canonical receipt proves them."""
    relative = str(row.get("manifest_path") or "")
    if not relative:
        return False
    base = root.resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        return False
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        isinstance(receipt, Mapping)
        and receipt.get("dataset_id") == row.get("dataset_id")
        and str(receipt.get("sha256") or "").lower() == str(row.get("sha256") or "").lower()
        and len(str(row.get("sha256") or "")) == 64
        and all(
            key not in row or receipt.get(key) == row.get(key)
            for key in ("replay_reason", "replay_schema_version")
        )
    )


def _compact_index_row(
    row: Mapping[str, Any], *, inherit_canonical_repo: bool = False,
    receipt_backed: bool = False,
    size_patch_proven: bool = False,
) -> dict[str, Any]:
    """Omit redundant fields, retaining all independent causal proofs.

    Immutable shard manifests retain the full original evidence. Only
    explicit booleans True can certify exact-count/replay eligibility.
    """
    direct = row.get("release_storage") != "zip_entry"
    out: dict[str, Any] = {}
    for key, value in row.items():
        if value is None or key in {"trade_identity_digests", "quality_reasons"}:
            continue
        # Duplicated human-readable diagnostics live in the immutable SHA-bound
        # per-shard manifest. Their removal from the search index never drops
        # replay compatibility or source provenance from its authoritative proof.
        if receipt_backed and key in {"replay_reason", "replay_schema_version"}:
            continue
        # The independent measurement patch already preserves these exact
        # scalar values under the immutable asset SHA. Keep them in the index
        # whenever this independent proof is absent or mismatched.
        if size_patch_proven and key in {"uncompressed_bytes", "uncompressed_size_exact"}:
            continue
        if (inherit_canonical_repo and key == "release_repository"
                and value == CANONICAL_DATA_REPOSITORY):
            continue
        if key == "record_count" and value == row.get("event_count"):
            continue
        if key == "release_member" and value == row.get("release_asset"):
            continue
        if direct and key in {"release_remote_size", "release_remote_digest"}:
            continue
        if key in {"trade_count_exact", "unique_trade_count_exact", "trade_identity_digests_exact"} and value is False:
            continue
        if key == "trade_count" and value == 0 and row.get("trade_count_exact") is not True:
            continue
        if key == "duplicate_count" and value == 0:
            continue
        out[key] = value
    return out


def _compact_run_manifest_tag_locators(
    index: dict[str, Any], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Factor repeated run tags into the *same* canonical index, reversibly.

    Only fully homogeneous physical-Release groups may use the root mapping;
    mixed or incomplete groups retain their explicit per-shard run tag.
    The mapping is not inferred from release naming conventions.
    """
    groups: dict[str, set[str | None]] = {}
    for row in rows:
        physical = str(row.get("release_tag") or "")
        if physical:
            canonical = row.get("run_manifest_release_tag")
            groups.setdefault(physical, set()).add(
                str(canonical) if isinstance(canonical, str) and canonical else None
            )
    aliases = {
        physical: next(iter(values))
        for physical, values in groups.items()
        if len(values) == 1 and None not in values
        and next(iter(values)) != physical
    }
    if aliases:
        index["run_manifest_release_tags_by_release"] = dict(sorted(aliases.items()))
    else:
        index.pop("run_manifest_release_tags_by_release", None)
    result: list[dict[str, Any]] = []
    for row in rows:
        value = dict(row)
        if value.get("release_tag") in aliases:
            value.pop("run_manifest_release_tag", None)
        result.append(value)
    return result


def _index_row(
    manifest: Mapping[str, Any], manifest_path: Path, root: Path, *,
    unique_patch_results: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
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
        "run_manifest_release_tag": manifest.get("run_manifest_release_tag"),
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
    unique_row = (
        unique_patch_results.get(str(manifest.get("dataset_id") or ""))
        if unique_patch_results is not None else None
    )
    if (
        isinstance(unique_row, Mapping)
        and manifest.get("trade_count_exact") is True
        and type(manifest.get("trade_count")) is int
        and len(str(manifest.get("sha256") or "")) == 64
        and str(unique_row.get("asset_sha256") or "").lower()
            == str(manifest.get("sha256") or "").lower()
        and unique_row.get("unique_trade_count_exact") is True
        and type(unique_row.get("trade_count_scanned")) is int
        and unique_row["trade_count_scanned"] == manifest["trade_count"]
        and type(unique_row.get("unique_trade_count")) is int
        and 0 <= unique_row["unique_trade_count"] <= manifest["trade_count"]
    ):
        # Never attach a dataset-id-only receipt to an unrelated new asset.
        row["unique_trade_count"] = unique_row["unique_trade_count"]
        row["unique_trade_count_exact"] = True

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
    unique_patch_results = _load_global_unique_count_patch_results(base)
    size_proofs = _load_size_proofs(base)
    expanded_rows = hydrate_default_release_repository(index)
    index["release_repository_default"] = CANONICAL_DATA_REPOSITORY
    rows_by_id = {
        str(row.get("dataset_id")): dict(row)
        for row in expanded_rows
        if isinstance(row, Mapping) and row.get("dataset_id")
    }
    # Also compact PREEXISTING rows: old DATA_INDEX repeated the full trade
    # digest vectors, already ~77 MiB for only 11k rows. Immutable manifests
    # retain the original vectors for SHA-bound aggregate proof.
    rows_by_id = {
        key: _compact_index_row(
            old_row, inherit_canonical_repo=True,
            receipt_backed=(
                any(k in old_row for k in ("replay_reason", "replay_schema_version"))
                and _has_sha_bound_receipt(base, old_row)
            ),
            size_patch_proven=_size_proof_matches(old_row, size_proofs),
        )
        for key, old_row in rows_by_id.items()
    }

    imported = 0
    statuses: dict[str, int] = {}
    pending_manifests: dict[str, tuple[Path, dict[str, Any]]] = {}
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
            # A large run's canonical RUN_MANIFEST Release differs from the
            # physical data-part tag. Keep both coordinates for idempotent
            # reconciliation; the original physical asset tag remains intact.
            canonical_tag = str(payload.get("release_tag") or "").strip()
            if canonical_tag and canonical_tag != str(manifest.get("release_tag") or ""):
                manifest["run_manifest_release_tag"] = canonical_tag
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

            # Stage changes in memory first: the canonical index size guard
            # must fire before we move or overwrite any immutable shard
            # classification receipts in this checkout.
            destination = (
                base
                / "datasets"
                / _STAGE_BY_STATUS[status]
                / f"{dataset_id}.manifest.json"
            )
            pending_manifests[dataset_id] = (destination, manifest)
            rows_by_id[dataset_id] = _compact_index_row(
                _index_row(manifest, destination, base, unique_patch_results=unique_patch_results),
                inherit_canonical_repo=True,
                receipt_backed=True,
                size_patch_proven=_size_proof_matches(manifest, size_proofs),
            )
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
    index["shards"] = _compact_run_manifest_tag_locators(index, shards)
    index["active_data_status"] = active
    # Fail before attempting a GitHub push past its 100 MiB blob limit.
    _atomic_json(index_path, index)
    if index_path.stat().st_size >= 85 * 1024 * 1024:
        raise ValueError("DATA_INDEX_TOO_LARGE: shard the catalogue before publication; no SAFE evidence dropped")

    # Only after the index has passed the atomic size guard may shard
    # manifests be published. A failed guard cannot erase prior evidence.
    for dataset_id, (destination, manifest) in pending_manifests.items():
        _atomic_json(destination, manifest)
        for stage in set(_STAGE_BY_STATUS.values()):
            stale = base / "datasets" / stage / f"{dataset_id}.manifest.json"
            if stale != destination and stale.exists():
                stale.unlink()

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


def compact_existing_index(root: str | Path = ROOT) -> dict[str, Any]:
    """Losslessly remove repeated canonical repo locators only.

    The same immutable per-shard manifest retains full repository provenance.
    A foreign repository remains explicit so all consumers can refuse it.
    """
    base = Path(root)
    path = base / INDEX_PATH.relative_to(ROOT) if INDEX_PATH.is_absolute() else base / INDEX_PATH
    index = json.loads(path.read_text(encoding="utf-8"))
    expanded = hydrate_default_release_repository(index)
    for row in expanded:
        if str(row.get("release_repository") or "") != CANONICAL_DATA_REPOSITORY:
            raise ValueError("COMPACTION_REQUIRES_VERIFIED_CANONICAL_RELEASE_LOCATOR")
    index["release_repository_default"] = CANONICAL_DATA_REPOSITORY
    index["shards"] = _compact_run_manifest_tag_locators(index, [
        _compact_index_row(row, inherit_canonical_repo=True)
        for row in expanded
    ])
    # Exact and reversible for all existing fields except explicitly redundant
    # canonical release_repository, which is represented at the index root.
    expected = [_compact_index_row(row) for row in expanded]
    if hydrate_default_release_repository(index) != expected:
        raise ValueError("COMPACTION_PARITY_MISMATCH")
    before_size = path.stat().st_size
    _atomic_json(path, index)
    return {"shards": len(expanded), "before_bytes": before_size,
            "after_bytes": path.stat().st_size,
            "saved_bytes": before_size - path.stat().st_size}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Index verified dataset V2 RUN_MANIFEST release evidence."
    )
    parser.add_argument("run_manifests", nargs="*")
    parser.add_argument("--compact-existing", action="store_true",
                        help="losslessly compact canonical release locator metadata")
    args = parser.parse_args()
    if args.compact_existing:
        if args.run_manifests:
            parser.error("--compact-existing does not accept run manifests")
        result = compact_existing_index()
    elif args.run_manifests:
        result = index_run_manifests(args.run_manifests)
    else:
        parser.error("provide run manifests or --compact-existing")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())