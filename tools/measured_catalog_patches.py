"""Read and write SHA-bound measurement patch catalogs without oversized blobs.

Large exact measurement tables are partitioned into bounded JSON parts. The
root file stays the public contract and contains only metadata plus hashes and
counts for the referenced parts. No measurement is discarded or synthesized.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

MAX_INLINE_BYTES = 95_000_000
MAX_PART_BYTES = 8 * 1024 * 1024
_PARTITION_SCHEMA = "alina.measured_patch_partitioned.v1"
_KIND_DIRECTORY = {
    "sizes": "uncompressed-size-parts",
    "records": "record-count-parts",
}


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("MEASURED_PATCH_SYMLINK_TARGET")
    fd, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"MEASURED_PATCH_INVALID_ROOT:{path.name}")
    return value


def _validate_rows(rows: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, Mapping):
        raise ValueError("MEASURED_PATCH_INVALID_ROWS")
    result: dict[str, dict[str, Any]] = {}
    for key, value in rows.items():
        if not isinstance(key, str) or not key:
            raise ValueError("MEASURED_PATCH_INVALID_DATASET_ID")
        if not isinstance(value, Mapping):
            raise ValueError("MEASURED_PATCH_INVALID_ROW")
        if key in result:
            raise ValueError("MEASURED_PATCH_DUPLICATE_DATASET_ID")
        result[key] = dict(value)
    return result


def _schema_for(kind: str) -> str:
    if kind not in _KIND_DIRECTORY:
        raise ValueError(f"MEASURED_PATCH_UNKNOWN_KIND:{kind}")
    return _PARTITION_SCHEMA


def load_patch(path: Path, kind: str) -> dict[str, Any]:
    """Load an inline or partitioned exact measurement patch fail-closed."""
    path = Path(path)
    document = _load_json(path)
    if not document:
        return {}
    rows = document.get(kind)
    if document.get("schema") != _PARTITION_SCHEMA:
        if rows is None:
            return document
        document[kind] = _validate_rows(rows)
        return document

    if document.get("kind") != kind or document.get("schema") != _schema_for(kind):
        raise ValueError("MEASURED_PATCH_KIND_MISMATCH")
    directory = _KIND_DIRECTORY[kind]
    if document.get("partition_directory") != directory:
        raise ValueError("MEASURED_PATCH_DIRECTORY_MISMATCH")
    parts = document.get("partitions")
    if not isinstance(parts, list):
        raise ValueError("MEASURED_PATCH_INVALID_PARTITIONS")
    parts_dir = path.parent / directory
    if parts_dir.is_symlink():
        raise ValueError("MEASURED_PATCH_SYMLINK_DIRECTORY")

    combined: dict[str, dict[str, Any]] = {}
    for number, descriptor in enumerate(parts, 1):
        if not isinstance(descriptor, Mapping):
            raise ValueError("MEASURED_PATCH_INVALID_DESCRIPTOR")
        relative = descriptor.get("path")
        expected = f"{directory}/part-{number:06d}.json"
        if relative != expected:
            raise ValueError("MEASURED_PATCH_NONCANONICAL_PART")
        part_path = path.parent / relative
        if part_path.is_symlink() or not part_path.is_file():
            raise ValueError("MEASURED_PATCH_MISSING_PART")
        data = part_path.read_bytes()
        if descriptor.get("bytes") != len(data):
            raise ValueError("MEASURED_PATCH_PART_SIZE_MISMATCH")
        if descriptor.get("sha256") != hashlib.sha256(data).hexdigest():
            raise ValueError("MEASURED_PATCH_PART_DIGEST_MISMATCH")
        part_rows = _validate_rows(json.loads(data))
        if descriptor.get("row_count") != len(part_rows):
            raise ValueError("MEASURED_PATCH_PART_COUNT_MISMATCH")
        for dataset_id, value in part_rows.items():
            if dataset_id in combined:
                raise ValueError("MEASURED_PATCH_DUPLICATE_DATASET_ID")
            combined[dataset_id] = value

    if document.get("row_count") != len(combined):
        raise ValueError("MEASURED_PATCH_GLOBAL_COUNT_MISMATCH")
    result = {
        key: value
        for key, value in document.items()
        if key not in {"partitions", "partition_directory", "partition_max_bytes",
                       "row_count", "kind"}
    }
    result[kind] = dict(sorted(combined.items()))
    return result


def _partition_rows(
    rows: Mapping[str, Mapping[str, Any]], directory: str,
) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    descriptors: list[dict[str, Any]] = []
    files: dict[str, bytes] = {}
    batch: dict[str, Mapping[str, Any]] = {}
    for dataset_id, value in sorted(rows.items()):
        candidate = dict(batch)
        candidate[dataset_id] = value
        candidate_bytes = _json_bytes(candidate)
        if batch and len(candidate_bytes) > MAX_PART_BYTES:
            number = len(files) + 1
            relative = f"{directory}/part-{number:06d}.json"
            data = _json_bytes(batch)
            files[relative] = data
            descriptors.append({
                "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "row_count": len(batch),
            })
            batch = {dataset_id: value}
        else:
            batch = candidate
    if batch:
        number = len(files) + 1
        relative = f"{directory}/part-{number:06d}.json"
        data = _json_bytes(batch)
        if len(data) > MAX_PART_BYTES:
            raise ValueError("MEASURED_PATCH_SINGLE_ROW_OVERSIZE")
        files[relative] = data
        descriptors.append({
            "path": relative,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "row_count": len(batch),
        })
    return descriptors, files


def write_patch(path: Path, document: Mapping[str, Any], kind: str) -> dict[str, Any]:
    """Write an inline or partitioned patch, publishing the root last."""
    path = Path(path)
    rows = _validate_rows(document.get(kind, {}))
    inline = _json_bytes(dict(document))
    if len(inline) < MAX_INLINE_BYTES:
        _atomic_write(path, inline)
        return {"format": "INLINE", "rows": len(rows), "bytes": len(inline)}

    directory = _KIND_DIRECTORY[kind]
    descriptors, files = _partition_rows(rows, directory)
    root = {
        key: value for key, value in document.items() if key != kind
    }
    root.update({
        "schema": _PARTITION_SCHEMA,
        "kind": kind,
        "partition_directory": directory,
        "partition_max_bytes": MAX_PART_BYTES,
        "row_count": len(rows),
        "partitions": descriptors,
    })
    root_bytes = _json_bytes(root)
    if len(root_bytes) >= MAX_INLINE_BYTES:
        raise ValueError("MEASURED_PATCH_ROOT_OVERSIZE")
    parts_dir = path.parent / directory
    if parts_dir.is_symlink():
        raise ValueError("MEASURED_PATCH_SYMLINK_DIRECTORY")
    for relative, data in files.items():
        target = path.parent / relative
        if target.is_symlink():
            raise ValueError("MEASURED_PATCH_SYMLINK_PART")
        _atomic_write(target, data)
    _atomic_write(path, root_bytes)
    return {
        "format": "PARTITIONED",
        "rows": len(rows),
        "partitions": len(files),
        "root_bytes": len(root_bytes),
        "parts_bytes": sum(len(value) for value in files.values()),
    }
