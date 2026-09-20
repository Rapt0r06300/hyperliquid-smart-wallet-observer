from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from data_vault_core import (
    DEFAULT_INCLUDE_ROOTS,
    DEFAULT_RAW_CHUNK_SIZE,
    DEFAULT_SMALL_PACK_RAW_LIMIT,
    SCHEMA_INDEX,
    SCHEMA_SNAPSHOT,
    iter_candidates,
    load_gzip_json,
    remove_tree,
    scan_text_for_secret,
    sha256_file,
    snapshot_id_from_run,
    stable_copy,
    utc_now,
    write_gzip_json,
)

SUMMARY_NAME = "VAULT_SUMMARY.json"
SNAPSHOT_MANIFEST_NAME = "VAULT_SNAPSHOT_MANIFEST.json.gz"
FILE_INDEX_NAME = "VAULT_FILE_INDEX.json.gz"
PUBLISH_LIST_NAME = "VAULT_PUBLISH_ASSETS.json"


def _safe_asset_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return cleaned[:80].strip("._-") or "snapshot"


def _previous_files(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    files = payload.get("files")
    if not isinstance(files, dict):
        return {}
    return {
        str(path): dict(record)
        for path, record in files.items()
        if isinstance(record, dict)
    }


def _same_metadata(previous: dict[str, Any], size: int, mtime_ns: int) -> bool:
    return (
        int(previous.get("size") or -1) == int(size)
        and int(previous.get("mtime_ns") or -1) == int(mtime_ns)
        and bool(previous.get("sha256"))
        and bool(previous.get("release_tag"))
    )


def _record_for_zip(
    *,
    copied,
    release_tag: str,
    snapshot_id: str,
    asset_name: str,
) -> dict[str, Any]:
    return {
        "present_local": True,
        "last_seen_snapshot": snapshot_id,
        "size": copied.size,
        "sha256": copied.sha256,
        "mtime_ns": copied.mtime_ns,
        "snapshot_id": snapshot_id,
        "release_tag": release_tag,
        "storage": "zip_entry",
        "asset": asset_name,
        "member": copied.relative_path,
    }


def _record_for_chunks(
    *,
    copied,
    release_tag: str,
    snapshot_id: str,
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "present_local": True,
        "last_seen_snapshot": snapshot_id,
        "size": copied.size,
        "sha256": copied.sha256,
        "mtime_ns": copied.mtime_ns,
        "snapshot_id": snapshot_id,
        "release_tag": release_tag,
        "storage": "raw_chunks",
        "chunks": chunks,
    }


def _build_zip_packs(
    changed,
    *,
    assets_dir: Path,
    release_tag: str,
    snapshot_id: str,
    raw_limit: int,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    small = [item for item in changed if item.size <= raw_limit]
    records: dict[str, dict[str, Any]] = {}
    assets: list[dict[str, Any]] = []
    if not small:
        return records, assets

    batches: list[list[Any]] = []
    current: list[Any] = []
    current_bytes = 0
    for item in sorted(small, key=lambda row: row.relative_path.casefold()):
        if current and current_bytes + item.size > raw_limit:
            batches.append(current)
            current = []
            current_bytes = 0
        current.append(item)
        current_bytes += item.size
    if current:
        batches.append(current)

    total = len(batches)
    prefix = _safe_asset_component(snapshot_id)
    for number, batch in enumerate(batches, 1):
        name = f"vault_{prefix}_pack_{number:04d}_of_{total:04d}.zip"
        target = assets_dir / name
        with zipfile.ZipFile(
            target,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=1,
            allowZip64=True,
        ) as archive:
            for item in batch:
                archive.write(item.staged_path, arcname=item.relative_path)
        digest = sha256_file(target)
        assets.append(
            {
                "name": name,
                "size": target.stat().st_size,
                "sha256": digest,
                "kind": "zip_pack",
                "member_count": len(batch),
                "raw_member_bytes": sum(item.size for item in batch),
            }
        )
        for item in batch:
            records[item.relative_path] = _record_for_zip(
                copied=item,
                release_tag=release_tag,
                snapshot_id=snapshot_id,
                asset_name=name,
            )
    return records, assets


def _build_large_chunks(
    changed,
    *,
    assets_dir: Path,
    release_tag: str,
    snapshot_id: str,
    small_limit: int,
    chunk_size: int,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    large = [item for item in changed if item.size > small_limit]
    records: dict[str, dict[str, Any]] = {}
    assets: list[dict[str, Any]] = []
    prefix = _safe_asset_component(snapshot_id)

    for file_number, item in enumerate(
        sorted(large, key=lambda row: row.relative_path.casefold()),
        1,
    ):
        part_count = max(1, math.ceil(item.size / chunk_size))
        chunks: list[dict[str, Any]] = []
        with item.staged_path.open("rb") as source:
            for part in range(1, part_count + 1):
                name = (
                    f"vault_{prefix}_large_{file_number:04d}_"
                    f"part_{part:04d}_of_{part_count:04d}.bin"
                )
                target = assets_dir / name
                remaining = chunk_size
                with target.open("wb") as output:
                    while remaining > 0:
                        block = source.read(min(8 * 1024 * 1024, remaining))
                        if not block:
                            break
                        output.write(block)
                        remaining -= len(block)
                digest = sha256_file(target)
                chunk_record = {
                    "asset": name,
                    "part": part,
                    "size": target.stat().st_size,
                    "sha256": digest,
                }
                chunks.append(chunk_record)
                assets.append(
                    {
                        "name": name,
                        "size": target.stat().st_size,
                        "sha256": digest,
                        "kind": "raw_chunk",
                        "source_path": item.relative_path,
                        "part": part,
                        "parts": part_count,
                    }
                )
        records[item.relative_path] = _record_for_chunks(
            copied=item,
            release_tag=release_tag,
            snapshot_id=snapshot_id,
            chunks=chunks,
        )
    return records, assets


def build_snapshot(
    *,
    source_root: Path,
    output_root: Path,
    previous_index_path: Path | None,
    snapshot_id: str,
    release_tag: str,
    source_label: str,
    include_roots: tuple[str, ...],
    extra_exclude_prefixes: tuple[str, ...],
    small_pack_raw_limit: int,
    raw_chunk_size: int,
) -> dict[str, Any]:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    if output_root == source_root or source_root in output_root.parents:
        raise ValueError("output_root must be outside source_root")
    output_root.mkdir(parents=True, exist_ok=True)

    stage_root = output_root / "staged"
    assets_dir = output_root / "assets"
    remove_tree(stage_root)
    remove_tree(assets_dir)
    stage_root.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    previous_payload = (
        load_gzip_json(previous_index_path)
        if previous_index_path and previous_index_path.is_file()
        else {}
    )
    previous = _previous_files(previous_payload)

    seen: set[str] = set()
    current_index: dict[str, dict[str, Any]] = {}
    changed = []
    unstable: list[str] = []
    secrets_skipped: list[dict[str, str]] = []
    read_errors: list[str] = []
    unchanged_fast = 0
    unchanged_hash = 0
    candidate_files = 0
    candidate_bytes = 0

    for rel, source in iter_candidates(
        source_root,
        include_roots=include_roots,
        extra_exclude_prefixes=extra_exclude_prefixes,
    ):
        candidate_files += 1
        seen.add(rel)
        try:
            stat = source.stat()
        except OSError:
            read_errors.append(rel)
            continue
        candidate_bytes += int(stat.st_size)

        prior = previous.get(rel)
        if prior and _same_metadata(prior, stat.st_size, stat.st_mtime_ns):
            carried = dict(prior)
            carried["present_local"] = True
            carried["last_seen_snapshot"] = snapshot_id
            carried.pop("deleted_at_snapshot", None)
            current_index[rel] = carried
            unchanged_fast += 1
            continue

        destination = stage_root / "files" / Path(rel)
        copied = stable_copy(source, destination, rel)
        if copied is None:
            unstable.append(rel)
            continue

        secret_pattern = scan_text_for_secret(copied.staged_path)
        if secret_pattern:
            copied.staged_path.unlink(missing_ok=True)
            secrets_skipped.append(
                {
                    "path": rel,
                    "reason": "secret_pattern",
                }
            )
            continue

        if prior and str(prior.get("sha256") or "").lower() == copied.sha256.lower():
            carried = dict(prior)
            carried["present_local"] = True
            carried["last_seen_snapshot"] = snapshot_id
            carried.pop("deleted_at_snapshot", None)
            carried["size"] = copied.size
            carried["mtime_ns"] = copied.mtime_ns
            current_index[rel] = carried
            copied.staged_path.unlink(missing_ok=True)
            unchanged_hash += 1
            continue

        changed.append(copied)

    deleted = sorted(set(previous) - seen)
    for rel in deleted:
        carried = dict(previous[rel])
        carried["present_local"] = False
        carried["deleted_at_snapshot"] = snapshot_id
        current_index[rel] = carried

    zip_records, zip_assets = _build_zip_packs(
        changed,
        assets_dir=assets_dir,
        release_tag=release_tag,
        snapshot_id=snapshot_id,
        raw_limit=small_pack_raw_limit,
    )
    chunk_records, chunk_assets = _build_large_chunks(
        changed,
        assets_dir=assets_dir,
        release_tag=release_tag,
        snapshot_id=snapshot_id,
        small_limit=small_pack_raw_limit,
        chunk_size=raw_chunk_size,
    )
    current_index.update(zip_records)
    current_index.update(chunk_records)

    data_assets = zip_assets + chunk_assets
    changed_bytes = sum(item.size for item in changed)
    asset_bytes = sum(int(item["size"]) for item in data_assets)

    index_payload = {
        "schema": SCHEMA_INDEX,
        "generated_at_utc": utc_now(),
        "snapshot_id": snapshot_id,
        "latest_release_tag": release_tag,
        "source_label": source_label,
        "file_count": len(current_index),
        "present_local_file_count": sum(
            1 for record in current_index.values()
            if record.get("present_local", True) is True
        ),
        "archived_deleted_file_count": sum(
            1 for record in current_index.values()
            if record.get("present_local", True) is False
        ),
        "raw_bytes": sum(int(record.get("size") or 0) for record in current_index.values()),
        "files": dict(sorted(current_index.items())),
    }
    index_path = output_root / FILE_INDEX_NAME
    write_gzip_json(index_path, index_payload)

    snapshot_payload = {
        "schema": SCHEMA_SNAPSHOT,
        "snapshot_id": snapshot_id,
        "release_tag": release_tag,
        "created_at_utc": utc_now(),
        "source_label": source_label,
        "include_roots": list(include_roots),
        "candidate_files": candidate_files,
        "candidate_bytes": candidate_bytes,
        "current_index_files": len(current_index),
        "present_local_files": sum(
            1 for record in current_index.values()
            if record.get("present_local", True) is True
        ),
        "archived_deleted_files": sum(
            1 for record in current_index.values()
            if record.get("present_local", True) is False
        ),
        "changed_files": len(changed),
        "changed_bytes": changed_bytes,
        "unchanged_fast_metadata": unchanged_fast,
        "unchanged_after_hash": unchanged_hash,
        "deleted_paths": deleted,
        "unstable_paths": unstable,
        "read_errors": read_errors,
        "secrets_skipped": secrets_skipped,
        "data_assets": data_assets,
        "data_asset_count": len(data_assets),
        "data_asset_bytes": asset_bytes,
        "paper_only": True,
        "real_execution": False,
        "source_modified": False,
    }
    manifest_path = output_root / SNAPSHOT_MANIFEST_NAME
    write_gzip_json(manifest_path, snapshot_payload)

    summary = {
        "schema": "alina.data_vault.summary.v1",
        "snapshot_id": snapshot_id,
        "release_tag": release_tag,
        "created_at_utc": snapshot_payload["created_at_utc"],
        "candidate_files": candidate_files,
        "candidate_bytes": candidate_bytes,
        "current_index_files": len(current_index),
        "present_local_files": snapshot_payload["present_local_files"],
        "archived_deleted_files": snapshot_payload["archived_deleted_files"],
        "changed_files": len(changed),
        "changed_bytes": changed_bytes,
        "deleted_count": len(deleted),
        "unstable_count": len(unstable),
        "secret_skip_count": len(secrets_skipped),
        "read_error_count": len(read_errors),
        "data_asset_count": len(data_assets),
        "data_asset_bytes": asset_bytes,
        "previous_index_present": bool(previous),
        "paper_only": True,
        "real_execution": False,
    }
    summary_path = output_root / SUMMARY_NAME
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    publish = []
    for item in data_assets:
        publish.append(
            {
                "name": item["name"],
                "path": str(assets_dir / str(item["name"])),
                "size": int(item["size"]),
                "sha256": str(item["sha256"]),
                "kind": item["kind"],
            }
        )
    for path, kind in (
        (manifest_path, "snapshot_manifest"),
        (index_path, "file_index"),
        (summary_path, "summary"),
    ):
        publish.append(
            {
                "name": path.name,
                "path": str(path),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
                "kind": kind,
            }
        )

    publish_path = output_root / PUBLISH_LIST_NAME
    publish_path.write_text(
        json.dumps(
            {
                "schema": "alina.data_vault.publish_list.v1",
                "snapshot_id": snapshot_id,
                "release_tag": release_tag,
                "assets": publish,
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    remove_tree(stage_root)
    return {
        "summary": summary,
        "output_root": str(output_root),
        "publish_list": str(publish_path),
        "snapshot_manifest": str(manifest_path),
        "file_index": str(index_path),
        "summary_path": str(summary_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build an incremental, secret-filtered Alina Data Vault snapshot."
    )
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--previous-index", type=Path, default=None)
    parser.add_argument("--snapshot-id", default="")
    parser.add_argument("--release-tag", default="")
    parser.add_argument("--source-label", default="alina-project")
    parser.add_argument("--include-root", action="append", default=[])
    parser.add_argument("--exclude-prefix", action="append", default=[])
    parser.add_argument(
        "--small-pack-mib",
        type=int,
        default=DEFAULT_SMALL_PACK_RAW_LIMIT // (1024 * 1024),
    )
    parser.add_argument(
        "--raw-chunk-mib",
        type=int,
        default=DEFAULT_RAW_CHUNK_SIZE // (1024 * 1024),
    )
    args = parser.parse_args(argv)

    snapshot_id = args.snapshot_id or snapshot_id_from_run()
    release_tag = args.release_tag or f"alina-vault-{snapshot_id}"
    include_roots = tuple(args.include_root) or tuple(DEFAULT_INCLUDE_ROOTS)

    result = build_snapshot(
        source_root=args.source_root,
        output_root=args.output_root,
        previous_index_path=args.previous_index,
        snapshot_id=snapshot_id,
        release_tag=release_tag,
        source_label=str(args.source_label or 'alina-project'),
        include_roots=include_roots,
        extra_exclude_prefixes=tuple(args.exclude_prefix),
        small_pack_raw_limit=max(64, args.small_pack_mib) * 1024 * 1024,
        raw_chunk_size=max(64, args.raw_chunk_mib) * 1024 * 1024,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
