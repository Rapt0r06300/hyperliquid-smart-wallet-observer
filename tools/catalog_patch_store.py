#!/usr/bin/env python3
"""Lossless, hash-verified storage for catalog evidence tables.

Small legacy patch files remain readable. Large logical patches are written as
bounded, deterministic JSON parts with an atomic manifest published last.
Readers always return the same expanded logical object regardless of storage.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

PARTITIONED_SCHEMA = "alina.catalog_patch_partitioned.v1"
MAX_PARTITION_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
_PART_NAME = re.compile(r"part-(\d{6})-([0-9a-f]{16})\.json\Z")


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"CATALOG_PATCH_DUPLICATE_JSON_KEY:{key}")
        result[key] = value
    return result


def _dump(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def _parts_directory(path: Path) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")
    return f"{stem}-parts"


def _load_json(path: Path, *, reject_duplicate_keys: bool = True) -> Any:
    hook = _object_without_duplicate_keys if reject_duplicate_keys else None
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=hook)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"CATALOG_PATCH_UNREADABLE:{path.name}:{exc}") from exc


def read_catalog_patch(path: str | Path, *, expected_table: str | None = None) -> dict[str, Any]:
    """Read a legacy inline patch or reconstruct every verified partition."""
    source = Path(path)
    if source.is_symlink():
        raise ValueError(f"CATALOG_PATCH_FILE_UNSAFE:{source.name}")
    if not source.is_file():
        return {}
    size = source.stat().st_size
    # Existing inline patches can be tens of megabytes. Avoid building a huge
    # temporary list of key/value pairs in object_pairs_hook while retaining
    # strict duplicate detection for bounded manifests and partitions.
    document = _load_json(source, reject_duplicate_keys=size <= MAX_PARTITION_BYTES)
    if not isinstance(document, dict):
        raise ValueError(f"CATALOG_PATCH_NOT_OBJECT:{source.name}")
    storage = document.get("storage")
    if storage is None:
        if expected_table is not None and (
            expected_table not in document or not isinstance(document[expected_table], dict)
        ):
            raise ValueError(f"CATALOG_PATCH_TABLE_MALFORMED:{expected_table}")
        return document
    if not isinstance(storage, Mapping) or storage.get("format") != PARTITIONED_SCHEMA:
        raise ValueError(f"CATALOG_PATCH_STORAGE_FORMAT_INVALID:{source.name}")
    table = storage.get("table")
    if not isinstance(table, str) or (expected_table is not None and table != expected_table):
        raise ValueError(f"CATALOG_PATCH_TABLE_MISMATCH:{source.name}")
    directory_name = storage.get("directory")
    if not isinstance(directory_name, str) or directory_name != _parts_directory(source):
        raise ValueError(f"CATALOG_PATCH_DIRECTORY_INVALID:{source.name}")
    descriptors = storage.get("partitions")
    if not isinstance(descriptors, list):
        raise ValueError(f"CATALOG_PATCH_PARTITIONS_INVALID:{source.name}")
    if type(storage.get("entry_count")) is not int or storage["entry_count"] < 0:
        raise ValueError(f"CATALOG_PATCH_ENTRY_COUNT_INVALID:{source.name}")
    part_dir = source.parent / directory_name
    if part_dir.is_symlink() or (part_dir.exists() and not part_dir.is_dir()):
        raise ValueError(f"CATALOG_PATCH_DIRECTORY_UNSAFE:{source.name}")
    entries: dict[str, Any] = {}
    previous_name = ""
    previous_dataset_id = ""
    for expected_ordinal, descriptor in enumerate(descriptors):
        if not isinstance(descriptor, Mapping):
            raise ValueError(f"CATALOG_PATCH_DESCRIPTOR_INVALID:{source.name}")
        name = descriptor.get("name")
        match = _PART_NAME.fullmatch(name) if isinstance(name, str) else None
        if not match or name <= previous_name or int(match.group(1)) != expected_ordinal:
            raise ValueError(f"CATALOG_PATCH_PART_NAME_INVALID:{source.name}")
        previous_name = name
        part_path = part_dir / name
        if part_path.is_symlink() or not part_path.is_file():
            raise ValueError(f"CATALOG_PATCH_PART_MISSING_OR_UNSAFE:{name}")
        payload = part_path.read_bytes()
        expected_size = descriptor.get("size_bytes")
        expected_hash = descriptor.get("sha256")
        expected_entries = descriptor.get("entries")
        if (
            len(payload) > MAX_PARTITION_BYTES
            or type(expected_size) is not int
            or len(payload) != expected_size
            or not isinstance(expected_hash, str)
            or len(expected_hash) != 64
            or match.group(2) != expected_hash[:16]
            or hashlib.sha256(payload).hexdigest() != expected_hash
        ):
            raise ValueError(f"CATALOG_PATCH_PART_INTEGRITY_FAILURE:{name}")
        part = json.loads(payload.decode("utf-8"), object_pairs_hook=_object_without_duplicate_keys)
        if not isinstance(part, dict) or set(part) != {table} or not isinstance(part[table], dict):
            raise ValueError(f"CATALOG_PATCH_PART_SCHEMA_INVALID:{name}")
        values = part[table]
        if type(expected_entries) is not int or len(values) != expected_entries:
            raise ValueError(f"CATALOG_PATCH_PART_COUNT_MISMATCH:{name}")
        if list(values) != sorted(values) or (values and next(iter(values)) <= previous_dataset_id):
            raise ValueError(f"CATALOG_PATCH_PART_ORDER_INVALID:{name}")
        if values:
            previous_dataset_id = next(reversed(values))
        duplicate = entries.keys() & values.keys()
        if duplicate:
            raise ValueError(f"CATALOG_PATCH_DUPLICATE_ENTRY:{next(iter(duplicate))}")
        entries.update(values)
    if len(entries) != storage["entry_count"]:
        raise ValueError(f"CATALOG_PATCH_TOTAL_COUNT_MISMATCH:{source.name}")
    result = {key: value for key, value in document.items() if key != "storage"}
    result[table] = entries
    return result


def write_catalog_patch(
    path: str | Path,
    document: Mapping[str, Any],
    *,
    table: str,
    inline_limit_bytes: int = MAX_PARTITION_BYTES,
) -> None:
    """Atomically write an inline patch or a lossless bounded partition set."""
    target = Path(path)
    if not isinstance(document, Mapping) or not isinstance(document.get(table), Mapping):
        raise ValueError(f"CATALOG_PATCH_TABLE_MALFORMED:{table}")
    values = dict(document)
    values.pop("storage", None)
    rows = document[table]
    if any(not isinstance(key, str) for key in rows):
        raise ValueError(f"CATALOG_PATCH_ENTRY_KEY_INVALID:{table}")
    values[table] = rows
    part_dir_name = _parts_directory(target)
    part_dir = target.parent / part_dir_name

    empty_size = len(_dump({}))
    empty_document = dict(values)
    empty_document[table] = {}
    candidate_size = len(_dump(empty_document))
    candidate_count = 0
    inline_fits = candidate_size <= inline_limit_bytes
    if inline_fits:
        for key in sorted(rows):
            candidate_size += len(_dump({key: rows[key]})) - empty_size
            if candidate_count:
                candidate_size += 1
            candidate_count += 1
            if candidate_size > inline_limit_bytes:
                inline_fits = False
                break

    if inline_fits:
        inline_payload = _dump(values)
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_replace(target, inline_payload)
        _remove_managed_parts(part_dir, keep=set())
        return

    part_dir.mkdir(parents=True, exist_ok=True)
    if part_dir.is_symlink():
        raise ValueError(f"CATALOG_PATCH_DIRECTORY_UNSAFE:{target.name}")
    chunks: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    base_size = len(_dump({table: {}}))
    current_size = base_size
    for key in sorted(rows):
        entry_size = len(_dump({key: rows[key]})) - empty_size
        proposed_size = current_size + entry_size + (1 if current else 0)
        if proposed_size > MAX_PARTITION_BYTES:
            if not current:
                raise ValueError(f"CATALOG_PATCH_ENTRY_EXCEEDS_PARTITION_LIMIT:{key}")
            chunks.append(current)
            current = {key: rows[key]}
            current_size = base_size + entry_size
            if current_size > MAX_PARTITION_BYTES:
                raise ValueError(f"CATALOG_PATCH_ENTRY_EXCEEDS_PARTITION_LIMIT:{key}")
        else:
            current[key] = rows[key]
            current_size = proposed_size
    if current or not chunks:
        chunks.append(current)

    descriptors: list[dict[str, Any]] = []
    keep: set[str] = set()
    for ordinal, chunk in enumerate(chunks):
        payload = _dump({table: chunk})
        if len(payload) > MAX_PARTITION_BYTES:
            raise ValueError("CATALOG_PATCH_PARTITION_SIZE_INVARIANT_FAILED")
        digest = hashlib.sha256(payload).hexdigest()
        name = f"part-{ordinal:06d}-{digest[:16]}.json"
        keep.add(name)
        _atomic_replace(part_dir / name, payload)
        descriptors.append(
            {
                "name": name,
                "size_bytes": len(payload),
                "sha256": digest,
                "entries": len(chunk),
            }
        )
    manifest = dict(values)
    manifest.pop(table)
    manifest["storage"] = {
        "format": PARTITIONED_SCHEMA,
        "table": table,
        "directory": part_dir_name,
        "entry_count": len(rows),
        "partitions": descriptors,
    }
    payload = _dump(manifest)
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ValueError(f"CATALOG_PATCH_MANIFEST_EXCEEDS_LIMIT:{target.name}")
    _atomic_replace(target, payload)
    _remove_managed_parts(part_dir, keep=keep)


def _atomic_replace(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _remove_managed_parts(directory: Path, *, keep: set[str]) -> None:
    if not directory.exists():
        return
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"CATALOG_PATCH_DIRECTORY_UNSAFE:{directory.name}")
    for child in directory.iterdir():
        if _PART_NAME.fullmatch(child.name) and child.name not in keep:
            if child.is_symlink() or not child.is_file():
                raise ValueError(f"CATALOG_PATCH_PART_UNSAFE:{child.name}")
            child.unlink()
