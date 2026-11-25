"""Lossless, fail-closed reader and writer for the partitioned DATA_INDEX."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

SCHEMA = "alina.data_index_partitioned.v1"
MAX_PARTITION_BYTES = 8 * 1024 * 1024
_PART_PATH = re.compile(
    r"data-index-parts/part-([0-9]{6})(?:-([0-9a-f]{64}))?[.]json"
)


def index_file_sha256(index_path: str | Path) -> str:
    """Hash the exact published DATA_INDEX root bytes with bounded memory."""
    path = Path(index_path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("DATA_INDEX_SHA_SOURCE_UNAVAILABLE")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_index_sha256_binding(
    receipt: Mapping[str, Any], index_path: str | Path,
) -> str:
    """Fail closed unless a receipt is bound to the current index root bytes."""
    if not isinstance(receipt, Mapping):
        raise ValueError("DATA_INDEX_SHA_BINDING_RECEIPT_INVALID")
    observed = receipt.get("source_index_sha256")
    expected = index_file_sha256(index_path)
    if not isinstance(observed, str) or not re.fullmatch(r"[0-9a-f]{64}", observed):
        raise ValueError("DATA_INDEX_SHA_BINDING_MISSING_OR_INVALID")
    if observed != expected:
        raise ValueError("DATA_INDEX_SHA_BINDING_STALE")
    return expected


def immutable_partition_path(number: int, digest: str) -> str:
    """Name a new immutable partition by its exact SHA-256.

    Legacy ``part-NNNNNN.json`` paths remain readable. Writers use this form
    for changed bytes so the old DATA_INDEX root stays valid until one atomic
    root replacement points at the complete new set.
    """
    if type(number) is not int or number < 1:
        raise ValueError("PARTITION_PARITY_INVALID_NUMBER")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("PARTITION_PARITY_INVALID_DIGEST")
    return f"data-index-parts/part-{number:06d}-{digest}.json"


def is_canonical_partition_path(relative: Any, number: int, digest: Any) -> bool:
    """Accept a legacy path or an immutable hash-suffixed path for this row."""
    if not isinstance(relative, str) or type(number) is not int or number < 1:
        return False
    match = _PART_PATH.fullmatch(relative)
    if match is None or int(match.group(1)) != number:
        return False
    suffix = match.group(2)
    if suffix is None:
        return True
    return isinstance(digest, str) and suffix == digest


def _dataset_id_fingerprint(dataset_id: str) -> int:
    """Return a compact process-local key for fail-closed duplicate checks.

    Python's keyed string hash avoids retaining millions of full IDs or
    calculating a second cryptographic digest. A hash collision rejects the
    catalogue; it can never make two equal dataset IDs appear different. The
    value is temporary and is never persisted as provenance or evidence.
    """
    return hash(dataset_id)


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _publish_immutable_partition(destination: Path, content: bytes) -> None:
    """Install bytes at a new immutable path without replacing a raced file."""
    import os
    import tempfile

    destination = Path(destination)
    if destination.is_symlink():
        raise ValueError("PARTITION_PARITY_SYMLINK_DESTINATION")
    if destination.exists():
        if not destination.is_file() or destination.read_bytes() != content:
            raise ValueError("PARTITION_PARITY_IMMUTABLE_PATH_COLLISION")
        return

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # Hard-link creation is atomic and fails if another writer already
            # installed this content-addressed name; os.replace would overwrite
            # an immutable path in that race.
            os.link(temporary, destination)
        except FileExistsError:
            if (destination.is_symlink() or not destination.is_file()
                    or destination.read_bytes() != content):
                raise ValueError("PARTITION_PARITY_IMMUTABLE_PATH_COLLISION") from None
    finally:
        temporary.unlink(missing_ok=True)


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
    parts_dir = index_path.parent / "data-index-parts"
    if parts_dir.is_symlink():
        raise ValueError("PARTITION_PARITY_UNSAFE_DIRECTORY")
    for i, descriptor in enumerate(parts, 1):
        if not isinstance(descriptor, dict):
            raise ValueError("PARTITION_PARITY_INVALID_DESCRIPTOR")
        path = descriptor.get("path")
        if not isinstance(path, str) or not _PART_PATH.fullmatch(path):
            raise ValueError("PARTITION_PARITY_INVALID_PATH")
        if not is_canonical_partition_path(path, i, descriptor.get("sha256")):
            raise ValueError("PARTITION_PARITY_NONCANONICAL_SEQUENCE")
        file_path = index_path.parent / path
        if file_path.is_symlink() or not file_path.is_file():
            raise ValueError("PARTITION_PARITY_MISSING_FILE")
        # Read once and derive the size from the exact bytes being hashed and
        # decoded.  This removes a filesystem stat per partition without
        # weakening the size/hash/parity checks (and avoids a TOCTOU gap
        # between stat() and read_bytes()).
        data = file_path.read_bytes()
        size = len(data)
        if (isinstance(descriptor.get("bytes"), bool)
                or descriptor.get("bytes") != size or size > limit):
            raise ValueError("PARTITION_PARITY_SIZE_MISMATCH")
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


def iter_index_rows(
    index_path: Path, *, progress_callback: Callable[[int, int], None] | None = None,
):
    """Yield every verified row without materializing a partitioned catalogue.

    The iterator validates each partition as it is consumed and validates the
    global count, dataset-id uniqueness, and SHA-bound concatenation before it
    is exhausted.  Callers that need a fully verified result must consume the
    iterator to completion; no partial catalogue is ever returned as a valid
    result.
    """
    index_path = Path(index_path)
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("DATA_INDEX_INVALID_ROOT")
    if raw.get("schema") != SCHEMA:
        if "partitions" in raw or not isinstance(raw.get("shards"), list):
            raise ValueError("DATA_INDEX_UNKNOWN_OR_PARTIAL_LAYOUT")
        _validate_rows(raw["shards"])
        yield from raw["shards"]
        return

    limit = raw.get("partition_max_bytes")
    count = raw.get("shard_count")
    parts = raw.get("partitions")
    expected_digest = raw.get("shards_sha256")
    legacy_schema = raw.get("legacy_schema")
    if (
        isinstance(limit, bool) or not isinstance(limit, int)
        or not 4 <= limit <= MAX_PARTITION_BYTES
        or isinstance(count, bool) or not isinstance(count, int) or count < 0
        or not isinstance(parts, list)
        or not isinstance(legacy_schema, str) or not legacy_schema
        or not isinstance(expected_digest, str)
    ):
        raise ValueError("PARTITION_PARITY_INVALID_METADATA")

    parts_dir = index_path.parent / "data-index-parts"
    if parts_dir.is_symlink():
        raise ValueError("PARTITION_PARITY_UNSAFE_DIRECTORY")
    seen_fingerprints: set[int] = set()
    observed_count = 0
    global_digest = hashlib.sha256(b"[")
    has_global_rows = False
    for number, descriptor in enumerate(parts, 1):
        if not isinstance(descriptor, dict):
            raise ValueError("PARTITION_PARITY_INVALID_DESCRIPTOR")
        relative = descriptor.get("path")
        if not isinstance(relative, str) or not _PART_PATH.fullmatch(relative):
            raise ValueError("PARTITION_PARITY_INVALID_PATH")
        if not is_canonical_partition_path(relative, number, descriptor.get("sha256")):
            raise ValueError("PARTITION_PARITY_NONCANONICAL_SEQUENCE")
        part_path = index_path.parent / relative
        if (
            part_path.is_symlink() or not part_path.is_file()
        ):
            raise ValueError("PARTITION_PARITY_MISSING_FILE")
        # Read once and derive the size from the exact bytes being hashed and
        # decoded.  This removes a filesystem stat per partition without
        # weakening the size/hash/parity checks (and avoids a TOCTOU gap
        # between stat() and read_bytes()).
        data = part_path.read_bytes()
        size = len(data)
        if (
            isinstance(descriptor.get("bytes"), bool)
            or descriptor.get("bytes") != size or size > limit
        ):
            raise ValueError("PARTITION_PARITY_SIZE_MISMATCH")
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
            # json.loads already returns plain dictionaries.  Avoid copying
            # 1.85M rows while streaming; callers receive fresh decoded data,
            # and the SHA/count checks below remain bound to the raw bytes.
            row = item
            identity = row.get("dataset_id")
            if not isinstance(identity, str) or not identity:
                raise ValueError("PARTITION_PARITY_DUPLICATE_OR_MISSING_DATASET_ID")
            fingerprint = _dataset_id_fingerprint(identity)
            if fingerprint in seen_fingerprints:
                # Includes both exact duplicates and digest collisions; fail closed.
                raise ValueError("PARTITION_PARITY_DUPLICATE_OR_MISSING_DATASET_ID")
            seen_fingerprints.add(fingerprint)
            observed_count += 1
            yield row
        if has_global_rows:
            global_digest.update(b",")
        global_digest.update(memoryview(data)[1:-2])
        has_global_rows = True
        if observed_count > count:
            raise ValueError("PARTITION_PARITY_COUNT_MISMATCH")
        if progress_callback is not None and (
            number == 1 or number % 10 == 0 or number == len(parts)
        ):
            progress_callback(number, len(parts))

    global_digest.update(b"]\n")
    if observed_count != count or global_digest.hexdigest() != expected_digest:
        raise ValueError("PARTITION_PARITY_GLOBAL_MISMATCH")



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
    seen_fingerprints: set[int] = set()
    observed_count = 0
    global_digest = hashlib.sha256()
    global_digest.update(b"[")
    has_global_rows = False
    parts_dir = index_path.parent / "data-index-parts"
    if parts_dir.is_symlink():
        raise ValueError("PARTITION_PARITY_UNSAFE_DIRECTORY")
    for index, descriptor in enumerate(descriptors, 1):
        if not isinstance(descriptor, dict):
            raise ValueError("PARTITION_PARITY_INVALID_DESCRIPTOR")
        relative = descriptor.get("path")
        if not isinstance(relative, str) or not _PART_PATH.fullmatch(relative):
            raise ValueError("PARTITION_PARITY_INVALID_PATH")
        if not is_canonical_partition_path(relative, index, descriptor.get("sha256")):
            raise ValueError("PARTITION_PARITY_NONCANONICAL_SEQUENCE")
        part_path = index_path.parent / relative
        if (
            part_path.is_symlink() or not part_path.is_file()
        ):
            raise ValueError("PARTITION_PARITY_MISSING_FILE")
        # Read once and derive the size from the exact bytes being hashed and
        # decoded.  This removes a filesystem stat per partition without
        # weakening the size/hash/parity checks (and avoids a TOCTOU gap
        # between stat() and read_bytes()).
        data = part_path.read_bytes()
        size = len(data)
        if (
            isinstance(descriptor.get("bytes"), bool)
            or descriptor.get("bytes") != size or size > limit
        ):
            raise ValueError("PARTITION_PARITY_SIZE_MISMATCH")
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
            if not isinstance(ident, str) or not ident:
                raise ValueError("PARTITION_PARITY_DUPLICATE_OR_MISSING_DATASET_ID")
            fingerprint = _dataset_id_fingerprint(ident)
            if fingerprint in seen_fingerprints:
                # Includes exact duplicates and digest collisions; fail closed.
                raise ValueError("PARTITION_PARITY_DUPLICATE_OR_MISSING_DATASET_ID")
            seen_fingerprints.add(fingerprint)
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
    existing: dict[str, Any] = {}
    original_root_bytes = index_path.read_bytes() if index_path.is_file() else None
    if index_path.is_file():
        existing = json.loads(original_root_bytes)
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
        if index_path.is_file() and index_path.read_bytes() != original_root_bytes:
            raise ValueError("PARTITION_PARITY_CONCURRENT_ROOT_CHANGE")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{index_path.name}.", suffix=".publish.tmp", dir=index_path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(inline)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, index_path)
        finally:
            temporary.unlink(missing_ok=True)
        return {"format": "INLINE", "shards": len(logical_index["shards"]),
                "index_bytes": len(inline)}

    root, legacy_parts = partition_index(
        logical_index, max_partition_bytes=max_partition_bytes,
    )
    index_path.parent.mkdir(parents=True, exist_ok=True)
    # Refuse a pre-existing link at the partition directory before writing
    # anything. Checking only each final part misses parent-symlink escapes.
    base = index_path.parent / "data-index-parts"
    if base.is_symlink():
        raise ValueError("PARTITION_PARITY_SYMLINK_DIRECTORY")
    old_descriptors = (
        existing.get("partitions", [])
        if current_partitioned and isinstance(existing.get("partitions"), list)
        else []
    )
    parts: dict[str, bytes] = {}
    reused_paths: set[str] = set()
    for number, descriptor in enumerate(root["partitions"], 1):
        legacy_path = descriptor["path"]
        content = legacy_parts[legacy_path]
        digest = descriptor["sha256"]
        old = old_descriptors[number - 1] if number <= len(old_descriptors) else None
        if (
            isinstance(old, Mapping)
            and old.get("sha256") == digest
            and old.get("bytes") == len(content)
            and old.get("row_count") == descriptor["row_count"]
            and is_canonical_partition_path(old.get("path"), number, digest)
        ):
            relative = str(old["path"])
            reused_paths.add(relative)
        else:
            relative = immutable_partition_path(number, digest)
        descriptor["path"] = relative
        parts[relative] = content

    with tempfile.TemporaryDirectory(prefix=".catalog-partition-stage-", dir=index_path.parent) as td:
        stage = Path(td)
        staged_root = stage / "DATA_INDEX.json"
        staged_root.write_bytes(_json_bytes(root))
        for rel, content in parts.items():
            file = stage / rel
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(content)
        verified_rows = sum(1 for _ in iter_index_rows(staged_root))
        if verified_rows != root["shard_count"]:
            raise ValueError("PARTITION_PARITY_STAGED_WRITE_MISMATCH")
        # Every content-addressed part is immutable. A crash while publishing
        # leaves the old root and its old parts intact; unreferenced new parts
        # are harmless and retained for later verification/reuse.
        for rel, content in parts.items():
            destination = index_path.parent / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            if rel in reused_paths:
                if destination.is_symlink() or not destination.is_file():
                    raise ValueError("PARTITION_PARITY_MISSING_FILE")
                continue
            _publish_immutable_partition(destination, content)
        # Stage validation proves every descriptor and generated partition;
        # newly installed paths are exact-byte hard links, while reused paths
        # were verified with the old root above. The root replace is the only
        # publication boundary and requires no second full-catalogue read.
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{index_path.name}.", suffix=".publish.tmp", dir=index_path.parent,
        )
        temporary_root = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(_json_bytes(root))
                handle.flush()
                os.fsync(handle.fileno())
            if json.loads(temporary_root.read_bytes()) != root:
                raise ValueError("PARTITION_PARITY_STAGED_WRITE_MISMATCH")
            if index_path.is_file() and index_path.read_bytes() != original_root_bytes:
                raise ValueError("PARTITION_PARITY_CONCURRENT_ROOT_CHANGE")
            os.replace(temporary_root, index_path)
        finally:
            temporary_root.unlink(missing_ok=True)
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
