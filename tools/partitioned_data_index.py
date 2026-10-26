"""Lossless, fail-closed partition format for a future DATA_INDEX migration.

This module does not publish or activate a partitioned catalogue. The existing
DATA_INDEX.json remains authoritative until *all* readers, writers, replay,
metrics, selection and SAFE restore paths are migrated and parity-gated.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

SCHEMA = "alina.data_index_partitioned.v1"
MAX_PARTITION_BYTES = 8 * 1024 * 1024
_PART_PATH = re.compile(r"data-index-parts/part-([0-9]{6})[.]json")


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _validate_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError("PARTITION_PARITY_INVALID_ROWS")
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, Mapping):
            raise ValueError("PARTITION_PARITY_INVALID_ROW")
        row = dict(item)
        ident = row.get("dataset_id")
        if not isinstance(ident, str) or not ident or ident in seen:
            raise ValueError("PARTITION_PARITY_DUPLICATE_OR_MISSING_DATASET_ID")
        seen.add(ident)
        validated.append(row)
    return validated


def partition_index(
    index: Mapping[str, Any], *, max_partition_bytes: int = MAX_PARTITION_BYTES
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Build a deterministic in-memory plan; never mutate the live index."""
    if (isinstance(max_partition_bytes, bool)
            or not isinstance(max_partition_bytes, int)
            or not 4 <= max_partition_bytes <= MAX_PARTITION_BYTES):
        raise ValueError("PARTITION_PARITY_INVALID_LIMIT")
    if not isinstance(index, Mapping):
        raise ValueError("PARTITION_PARITY_INVALID_INDEX")
    if any(k in index for k in (
        "partitions", "legacy_schema", "shard_count", "shards_sha256",
        "partition_max_bytes"
    )):
        raise ValueError("PARTITION_PARITY_RESERVED_METADATA")
    legacy_schema = index.get("schema")
    if not isinstance(legacy_schema, str) or not legacy_schema or legacy_schema == SCHEMA:
        raise ValueError("PARTITION_PARITY_INVALID_LEGACY_SCHEMA")
    rows = _validate_rows(index.get("shards"))
    result = {k: v for k, v in index.items() if k not in ("shards", "schema")}
    result.update({
        "schema": SCHEMA,
        "legacy_schema": legacy_schema,
        "partition_max_bytes": max_partition_bytes,
        "shard_count": len(rows),
        "shards_sha256": hashlib.sha256(_json_bytes(rows)).hexdigest(),
        "partitions": [],
    })
    files: dict[str, bytes] = {}
    batch: list[dict[str, Any]] = []
    current_bytes = 3  # '[' + ']' + newline
    def flush() -> None:
        nonlocal batch, current_bytes
        if not batch:
            return
        path = f"data-index-parts/part-{len(files) + 1:06d}.json"
        data = _json_bytes(batch)
        if len(data) > max_partition_bytes:
            raise ValueError("PARTITION_PARITY_OVERSIZE")
        files[path] = data
        result["partitions"].append({
            "path": path, "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "row_count": len(batch),
        })
        batch = []
        current_bytes = 3

    for row in rows:
        encoded_len = len(_json_bytes(row)) - 1
        added = encoded_len + (1 if batch else 0)
        if current_bytes + added > max_partition_bytes:
            flush()
        if 3 + encoded_len > max_partition_bytes:
            raise ValueError("PARTITION_PARITY_SINGLE_ROW_OVERSIZE")
        batch.append(row)
        current_bytes += encoded_len + (1 if len(batch) > 1 else 0)
    flush()
    return result, files


def load_partitioned_index(
    index_path: Path, *, progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Reconstruct the exact original logical index; refuse any missing evidence.

    Callers must not fall back to an incomplete or partial index on failure.
    """
    index_path = Path(index_path)
    root = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(root, dict) or root.get("schema") != SCHEMA or "shards" in root:
        raise ValueError("PARTITION_PARITY_INVALID_ROOT")
    limit = root.get("partition_max_bytes")
    count = root.get("shard_count")
    parts = root.get("partitions")
    legacy_schema = root.get("legacy_schema")
    if (isinstance(limit, bool) or not isinstance(limit, int)
            or not 4 <= limit <= MAX_PARTITION_BYTES
            or isinstance(count, bool) or not isinstance(count, int) or count < 0
            or not isinstance(parts, list)
            or not isinstance(legacy_schema, str) or not legacy_schema
            or not isinstance(root.get("shards_sha256"), str)):
        raise ValueError("PARTITION_PARITY_INVALID_METADATA")
    rows: list[dict[str, Any]] = []
    seen_dataset_ids: set[str] = set()
    global_digest = hashlib.sha256()
    global_digest.update(b"[")
    has_global_rows = False
    for i, descriptor in enumerate(parts, 1):
        if not isinstance(descriptor, dict):
            raise ValueError("PARTITION_PARITY_INVALID_DESCRIPTOR")
        path = descriptor.get("path")
        if not isinstance(path, str) or not _PART_PATH.fullmatch(path):
            raise ValueError("PARTITION_PARITY_INVALID_PATH")
        if path != f"data-index-parts/part-{i:06d}.json":
            raise ValueError("PARTITION_PARITY_NONCANONICAL_SEQUENCE")
        # Do not let a partition directory symlink redirect a supposedly
        # canonical read outside catalog/, even when the inner file is regular.
        parts_dir = index_path.parent / "data-index-parts"
        if parts_dir.is_symlink():
            raise ValueError("PARTITION_PARITY_UNSAFE_DIRECTORY")
        file_path = index_path.parent / path
        if not file_path.resolve().is_relative_to(index_path.parent.resolve()):
            raise ValueError("PARTITION_PARITY_UNSAFE_DIRECTORY")
        if file_path.is_symlink() or not file_path.is_file():
            raise ValueError("PARTITION_PARITY_MISSING_FILE")
        size = file_path.stat().st_size
        if (isinstance(descriptor.get("bytes"), bool)
                or descriptor.get("bytes") != size or size > limit):
            raise ValueError("PARTITION_PARITY_SIZE_MISMATCH")
        data = file_path.read_bytes()
        if hashlib.sha256(data).hexdigest() != descriptor.get("sha256"):
            raise ValueError("PARTITION_PARITY_DIGEST_MISMATCH")
        part_rows = _validate_rows(json.loads(data))
        if (isinstance(descriptor.get("row_count"), bool)
                or len(part_rows) != descriptor.get("row_count") or not part_rows):
            raise ValueError("PARTITION_PARITY_COUNT_MISMATCH")
        for row in part_rows:
            identity = row["dataset_id"]
            if identity in seen_dataset_ids:
                raise ValueError("PARTITION_PARITY_DUPLICATE_OR_MISSING_DATASET_ID")
            seen_dataset_ids.add(identity)
        # partition_index writes canonical JSON arrays.  Their SHA-bound raw
        # interiors can therefore be joined into the canonical global array
        # without allocating and serializing the entire multi-GB catalogue a
        # second time.  A non-canonical part fails the global digest closed.
        if not data.startswith(b"[") or not data.endswith(b"]\n"):
            raise ValueError("PARTITION_PARITY_GLOBAL_MISMATCH")
        if has_global_rows:
            global_digest.update(b",")
        global_digest.update(memoryview(data)[1:-2])
        has_global_rows = True
        rows.extend(part_rows)
        if len(rows) > count:
            raise ValueError("PARTITION_PARITY_COUNT_MISMATCH")
        if progress_callback is not None and (i == 1 or i % 10 == 0 or i == len(parts)):
            progress_callback(i, len(parts))
    global_digest.update(b"]\n")
    if len(rows) != count or global_digest.hexdigest() != root["shards_sha256"]:
        raise ValueError("PARTITION_PARITY_GLOBAL_MISMATCH")
    reconstructed = {k: v for k, v in root.items() if k not in (
        "partitions", "legacy_schema", "shard_count", "shards_sha256",
        "partition_max_bytes", "schema"
    )}
    reconstructed["schema"] = legacy_schema
    reconstructed["shards"] = rows
    return reconstructed



def select_index_rows(
    index_path: Path,
    predicate: Callable[[Mapping[str, Any]], bool],
    *,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Select rows from a verified index without reconstructing its full list.

    Partitioned catalogs are parsed one bounded partition at a time. The
    complete global digest, row count, and dataset-ID uniqueness are checked
    before selected rows are returned.
    """
    index_path = Path(index_path)
    if index_path.is_symlink() or not index_path.is_file():
        raise ValueError("PARTITION_PARITY_UNSAFE_INDEX")
    root = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(root, dict):
        raise ValueError("DATA_INDEX_INVALID_ROOT")

    if root.get("schema") != SCHEMA:
        if "partitions" in root or not isinstance(root.get("shards"), list):
            raise ValueError("DATA_INDEX_UNKNOWN_OR_PARTIAL_LAYOUT")
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in root["shards"]:
            if not isinstance(item, Mapping):
                raise ValueError("PARTITION_PARITY_INVALID_ROW")
            row = dict(item)
            ident = row.get("dataset_id")
            if not isinstance(ident, str) or not ident or ident in seen:
                raise ValueError("PARTITION_PARITY_DUPLICATE_OR_MISSING_DATASET_ID")
            seen.add(ident)
            if predicate(row):
                selected.append(row)
        metadata = {key: value for key, value in root.items() if key != "shards"}
        if "_verified_shard_count" in metadata:
            raise ValueError("DATA_INDEX_RESERVED_METADATA")
        metadata["_verified_shard_count"] = len(seen)
        return metadata, selected

    limit = root.get("partition_max_bytes")
    count = root.get("shard_count")
    descriptors = root.get("partitions")
    legacy_schema = root.get("legacy_schema")
    expected_digest = root.get("shards_sha256")
    if (
        isinstance(limit, bool) or not isinstance(limit, int)
        or not 4 <= limit <= MAX_PARTITION_BYTES
        or isinstance(count, bool) or not isinstance(count, int) or count < 0
        or not isinstance(descriptors, list)
        or not isinstance(legacy_schema, str) or not legacy_schema
        or not isinstance(expected_digest, str)
    ):
        raise ValueError("PARTITION_PARITY_INVALID_METADATA")

    selected = []
    seen: set[str] = set()
    observed_count = 0
    global_digest = hashlib.sha256()
    global_digest.update(b"[")
    has_global_rows = False
    for index, descriptor in enumerate(descriptors, 1):
        if not isinstance(descriptor, dict):
            raise ValueError("PARTITION_PARITY_INVALID_DESCRIPTOR")
        relative = descriptor.get("path")
        if not isinstance(relative, str) or not _PART_PATH.fullmatch(relative):
            raise ValueError("PARTITION_PARITY_INVALID_PATH")
        if relative != f"data-index-parts/part-{index:06d}.json":
            raise ValueError("PARTITION_PARITY_NONCANONICAL_SEQUENCE")
        parts_dir = index_path.parent / "data-index-parts"
        if parts_dir.is_symlink():
            raise ValueError("PARTITION_PARITY_UNSAFE_DIRECTORY")
        part_path = index_path.parent / relative
        if (
            not part_path.resolve().is_relative_to(index_path.parent.resolve())
            or part_path.is_symlink() or not part_path.is_file()
        ):
            raise ValueError("PARTITION_PARITY_MISSING_FILE")
        size = part_path.stat().st_size
        if (
            isinstance(descriptor.get("bytes"), bool)
            or descriptor.get("bytes") != size or size > limit
        ):
            raise ValueError("PARTITION_PARITY_SIZE_MISMATCH")
        data = part_path.read_bytes()
        if hashlib.sha256(data).hexdigest() != descriptor.get("sha256"):
            raise ValueError("PARTITION_PARITY_DIGEST_MISMATCH")
        if not data.startswith(b"[") or not data.endswith(b"]\n"):
            raise ValueError("PARTITION_PARITY_GLOBAL_MISMATCH")
        part_rows = json.loads(data)
        if (
            not isinstance(part_rows, list) or not part_rows
            or isinstance(descriptor.get("row_count"), bool)
            or len(part_rows) != descriptor.get("row_count")
        ):
            raise ValueError("PARTITION_PARITY_COUNT_MISMATCH")
        for item in part_rows:
            if not isinstance(item, Mapping):
                raise ValueError("PARTITION_PARITY_INVALID_ROW")
            row = dict(item)
            ident = row.get("dataset_id")
            if not isinstance(ident, str) or not ident or ident in seen:
                raise ValueError("PARTITION_PARITY_DUPLICATE_OR_MISSING_DATASET_ID")
            seen.add(ident)
            observed_count += 1
            if predicate(row):
                selected.append(row)
        if has_global_rows:
            global_digest.update(b",")
        global_digest.update(memoryview(data)[1:-2])
        has_global_rows = True
        if observed_count > count:
            raise ValueError("PARTITION_PARITY_COUNT_MISMATCH")
        if progress_callback is not None and (
            index == 1 or index % 10 == 0 or index == len(descriptors)
        ):
            progress_callback(index, len(descriptors))
    global_digest.update(b"]\n")
    if observed_count != count or global_digest.hexdigest() != expected_digest:
        raise ValueError("PARTITION_PARITY_GLOBAL_MISMATCH")

    metadata = {
        key: value for key, value in root.items()
        if key not in {
            "partitions", "legacy_schema", "shard_count", "shards_sha256",
            "partition_max_bytes", "schema",
        }
    }
    if "_verified_shard_count" in metadata:
        raise ValueError("PARTITION_PARITY_RESERVED_METADATA")
    metadata["_verified_shard_count"] = observed_count
    metadata["schema"] = legacy_schema
    return metadata, selected


def read_index(
    index_path: Path, *, progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Return the complete logical index, legacy or fully verified partitions.

    No partial shard list or silent fallback is permitted.
    """
    index_path = Path(index_path)
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("DATA_INDEX_INVALID_ROOT")
    if raw.get("schema") == SCHEMA:
        return load_partitioned_index(index_path, progress_callback=progress_callback)
    if "partitions" in raw or not isinstance(raw.get("shards"), list):
        raise ValueError("DATA_INDEX_UNKNOWN_OR_PARTIAL_LAYOUT")
    _validate_rows(raw["shards"])
    return raw



def save_index(
    index_path: Path,
    logical_index: Mapping[str, Any],
    *,
    max_inline_bytes: int = 85 * 1024 * 1024,
    max_partition_bytes: int = MAX_PARTITION_BYTES,
) -> dict[str, Any]:
    """Write complete index in small inline form or SHA-verified partitions.

    The caller must include the root and all referenced parts in a single
    Git commit. A failed checkout is never pushed by the reconciliation job.
    Never silently truncate shards, promote SAFE, or override a partitioned
    root with an inline index.
    """
    import os
    import tempfile

    index_path = Path(index_path)
    if max_inline_bytes < 1024:
        raise ValueError("PARTITION_PARITY_INVALID_INLINE_LIMIT")
    current_partitioned = False
    if index_path.is_file():
        existing = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            raise ValueError("PARTITION_PARITY_EXISTING_ROOT_INVALID")
        # Validate every existing layout, not only the partitioned one.
        # An unknown/partial root must never be overwritten as if it were
        # an ordinary inline index: doing so could discard evidence.
        read_index(index_path)
        current_partitioned = existing.get("schema") == SCHEMA
    inline = _json_bytes(dict(logical_index))
    if not current_partitioned and len(inline) < max_inline_bytes:
        _validate_rows(logical_index.get("shards"))
        index_path.parent.mkdir(parents=True, exist_ok=True)
        temp = index_path.with_suffix(index_path.suffix + ".publish.tmp")
        temp.write_bytes(inline)
        os.replace(temp, index_path)
        return {"format": "INLINE", "shards": len(logical_index["shards"]),
                "index_bytes": len(inline)}

    root, parts = partition_index(logical_index, max_partition_bytes=max_partition_bytes)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    # Refuse a pre-existing link at the partition directory before writing
    # anything. Checking only each final part misses parent-symlink escapes.
    if (index_path.parent / "data-index-parts").is_symlink():
        raise ValueError("PARTITION_PARITY_SYMLINK_DIRECTORY")
    with tempfile.TemporaryDirectory(prefix=".catalog-partition-stage-", dir=index_path.parent) as td:
        stage = Path(td)
        staged_root = stage / "DATA_INDEX.json"
        staged_root.write_bytes(_json_bytes(root))
        for rel, content in parts.items():
            file = stage / rel
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(content)
        if load_partitioned_index(staged_root) != dict(logical_index):
            raise ValueError("PARTITION_PARITY_STAGED_WRITE_MISMATCH")
        # Git publication is the atomic boundary. No incomplete working-tree
        # state is ever committed; every single part is checked before root.
        for rel, content in parts.items():
            destination = index_path.parent / rel
            if destination.is_symlink():
                raise ValueError("PARTITION_PARITY_SYMLINK_DESTINATION")
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".publish.tmp")
            temporary.write_bytes(content)
            os.replace(temporary, destination)
        os.replace(staged_root, index_path)
    if read_index(index_path) != dict(logical_index):
        raise ValueError("PARTITION_PARITY_PUBLISHED_WRITE_MISMATCH")
    current_parts = set(parts)
    base = index_path.parent / "data-index-parts"
    # Prune *only* files matching the canonical format, leaving other
    # evidence untouched; the old bytes remain available in Git history.
    for obsolete in sorted(base.glob("part-*.json")):
        rel = obsolete.relative_to(index_path.parent).as_posix()
        if rel not in current_parts and obsolete.is_file() and not obsolete.is_symlink():
            obsolete.unlink()
    return {"format": "PARTITIONED", "shards": len(logical_index["shards"]),
            "partitions": len(parts),
            "root_bytes": index_path.stat().st_size,
            "parts_bytes": sum(map(len, parts.values()))}


def prove_partitioned_index(
    index_path: Path, output_directory: Path
) -> dict[str, Any]:
    """Prove byte-bound, exact logical reconstruction without replacing DATA_INDEX."""
    import os
    import tempfile

    index_path = Path(index_path).resolve()
    output_directory = Path(output_directory).resolve()
    if output_directory == index_path.parent or index_path.parent in output_directory.parents:
        raise ValueError("PARTITION_PARITY_OUTPUT_MUST_BE_OUTSIDE_SOURCE")
    if output_directory.exists():
        raise ValueError("PARTITION_PARITY_OUTPUT_ALREADY_EXISTS")
    source = index_path.read_bytes()
    source_layout = "PARTITIONED" if json.loads(source).get("schema") == SCHEMA else "INLINE"
    # Verify every original SHA-bound part; do not assume an inline index.
    original = read_index(index_path)
    root, parts = partition_index(original)
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".partition-proof-", dir=output_directory.parent) as tmp:
        stage = Path(tmp)
        path = stage / "DATA_INDEX.json"
        path.write_bytes(_json_bytes(root))
        for relative, data in parts.items():
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        reconstructed = load_partitioned_index(path)
        if reconstructed != original:
            raise ValueError("PARTITION_PARITY_RECONSTRUCTION_MISMATCH")
        report = {
            "schema": "alina.partition_parity_proof.v1",
            "status": "VERIFIED",
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "source_layout": source_layout,
            "original_shards": len(original["shards"]),
            "partitioned_shards": len(reconstructed["shards"]),
            "partition_count": len(parts),
            "partitions_sha256": root["shards_sha256"],
            "source_unchanged": hashlib.sha256(index_path.read_bytes()).digest()
                == hashlib.sha256(source).digest(),
            "paper_read_only": True,
        }
        if not report["source_unchanged"] or read_index(index_path) != original:
            raise ValueError("PARTITION_PARITY_SOURCE_CHANGED")
        (stage / "PARTITION_PROOF.json").write_bytes(_json_bytes(report))
        os.replace(stage, output_directory)
        return report


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Read-only DATA_INDEX partition parity proof")
    parser.add_argument("--index", type=Path, default=Path("catalog/DATA_INDEX.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prove_partitioned_index(args.index, args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
