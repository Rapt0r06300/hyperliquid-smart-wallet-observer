"""Lossless, fail-closed partition format for a future DATA_INDEX migration.

This module does not publish or activate a partitioned catalogue. The existing
DATA_INDEX.json remains authoritative until *all* readers, writers, replay,
metrics, selection and SAFE restore paths are migrated and parity-gated.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

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


def load_partitioned_index(index_path: Path) -> dict[str, Any]:
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
    for i, descriptor in enumerate(parts, 1):
        if not isinstance(descriptor, dict):
            raise ValueError("PARTITION_PARITY_INVALID_DESCRIPTOR")
        path = descriptor.get("path")
        if not isinstance(path, str) or not _PART_PATH.fullmatch(path):
            raise ValueError("PARTITION_PARITY_INVALID_PATH")
        if path != f"data-index-parts/part-{i:06d}.json":
            raise ValueError("PARTITION_PARITY_NONCANONICAL_SEQUENCE")
        file_path = index_path.parent / path
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
        rows.extend(part_rows)
        if len(rows) > count:
            raise ValueError("PARTITION_PARITY_COUNT_MISMATCH")
    rows = _validate_rows(rows)
    if len(rows) != count or hashlib.sha256(_json_bytes(rows)).hexdigest() != root["shards_sha256"]:
        raise ValueError("PARTITION_PARITY_GLOBAL_MISMATCH")
    reconstructed = {k: v for k, v in root.items() if k not in (
        "partitions", "legacy_schema", "shard_count", "shards_sha256",
        "partition_max_bytes", "schema"
    )}
    reconstructed["schema"] = legacy_schema
    reconstructed["shards"] = rows
    return reconstructed



def read_index(index_path: Path) -> dict[str, Any]:
    """Return the complete logical index, legacy or fully verified partitions.

    No partial shard list or silent fallback is permitted.
    """
    index_path = Path(index_path)
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("DATA_INDEX_INVALID_ROOT")
    if raw.get("schema") == SCHEMA:
        return load_partitioned_index(index_path)
    if "partitions" in raw or not isinstance(raw.get("shards"), list):
        raise ValueError("DATA_INDEX_UNKNOWN_OR_PARTIAL_LAYOUT")
    _validate_rows(raw["shards"])
    return raw


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
    original = json.loads(source)
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
            "original_shards": len(original["shards"]),
            "partitioned_shards": len(reconstructed["shards"]),
            "partition_count": len(parts),
            "partitions_sha256": root["shards_sha256"],
            "source_unchanged": hashlib.sha256(index_path.read_bytes()).digest()
                == hashlib.sha256(source).digest(),
            "paper_read_only": True,
        }
        if not report["source_unchanged"]:
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
