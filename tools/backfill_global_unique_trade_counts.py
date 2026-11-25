#!/usr/bin/env python3
"""Compute exact global unique trade counts without storing the identity universe in Git.

The previous implementation persisted every canonical trade identity in
TRADE_UNIQUE_COUNT_PATCH.json.  On real Dataset V2 volumes that file grows past
GitHub's 100 MiB blob limit, so otherwise-valid scans could never be published.
This implementation scans bounded batches of immutable trade assets, merges
full identities into a durable local SQLite checkpoint, and publishes only
compact counts and a deterministic digest. Missing/unavailable shards remain
explicit and coverage stays fail-closed.
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import json
import mmap
import os
import sqlite3
import tempfile
from collections.abc import Mapping
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

try:
    from tools.backfill_exact_trade_counts import (
        TRADE_FAMILIES,
        _download,
        _native_trade_keys,
    )
    from tools.global_unique_trade_patch import (
        SCHEMA_V5 as GLOBAL_UNIQUE_PATCH_SCHEMA,
    )
    from tools.global_unique_trade_patch import (
        compact_global_unique_count_rows,
    )
except ModuleNotFoundError:
    from backfill_exact_trade_counts import TRADE_FAMILIES, _download, _native_trade_keys
    from global_unique_trade_patch import (
        SCHEMA_V5 as GLOBAL_UNIQUE_PATCH_SCHEMA,
    )
    from global_unique_trade_patch import (
        compact_global_unique_count_rows,
    )

try:
    from tools.index_run_manifest import (
        CANONICAL_DATA_REPOSITORY,
        _atomic_json,
    )
except ModuleNotFoundError:
    from index_run_manifest import (
        CANONICAL_DATA_REPOSITORY,
        _atomic_json,
    )

try:
    from tools.partitioned_data_index import SCHEMA as PARTITION_SCHEMA
    from tools.partitioned_data_index import (
        _dataset_id_fingerprint,
        _json_bytes,
        _publish_immutable_partition,
        immutable_partition_path,
        is_canonical_partition_path,
        iter_index_rows,
    )
except ModuleNotFoundError:
    from partitioned_data_index import SCHEMA as PARTITION_SCHEMA
    from partitioned_data_index import (
        _dataset_id_fingerprint,
        _json_bytes,
        _publish_immutable_partition,
        immutable_partition_path,
        is_canonical_partition_path,
        iter_index_rows,
    )

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "catalog" / "DATA_INDEX.json"
PATCH_PATH = ROOT / "catalog" / "TRADE_UNIQUE_COUNT_PATCH.json"
EXACT_COUNT_PATCH_PATH = ROOT / "catalog" / "TRADE_COUNT_PATCH.json"
CHECKPOINT_PATH = ROOT / "runtime" / "reports" / "global-unique-trades" / "identities.sqlite"
IDENTITY_VERSION = "native-id-or-venue-family-symbol-time-side-price-size-v3-full-string"
MERGE_ORDER_VERSION = "dataset-id-ascending-v1"
MAX_IN_FLIGHT_RELEASE_BYTES = 768 * 1024 * 1024
MAX_JSONL_RECORD_BYTES = 64 * 1024 * 1024
CHECKPOINT_COMMIT_INTERVAL = 32
IDENTITY_INSERT_BATCH_SIZE = 4096
GLOBAL_UNIQUE_PATCH_MAX_BYTES = 95_000_000
_SCAN_ROW_KEYS = (
    "dataset_id", "family", "venue", "symbol", "trade_count",
    "trade_count_exact", "manifest_path", "release_repository",
    "release_tag", "release_asset", "release_container_asset",
    "release_member", "release_storage", "release_remote_size",
    "release_remote_digest", "sha256", "bytes",
)
_SCAN_ROW_INDEX = {key: index for index, key in enumerate(_SCAN_ROW_KEYS)}


def _skip_json_whitespace(data: mmap.mmap, offset: int) -> int:
    while offset < len(data) and data[offset] in b" \t\r\n":
        offset += 1
    return offset


def _json_string_end(data: mmap.mmap, offset: int) -> int:
    """Return the byte just after a JSON string, respecting escaped quotes."""
    if offset >= len(data) or data[offset] != ord('"'):
        raise ValueError("expected JSON string")
    cursor = offset + 1
    while True:
        quote = data.find(b'"', cursor)
        if quote < 0:
            raise ValueError("unterminated JSON string")
        slash = quote - 1
        while slash >= offset and data[slash] == ord("\\"):
            slash -= 1
        if (quote - slash - 1) % 2 == 0:
            return quote + 1
        cursor = quote + 1


def _json_value_end(data: mmap.mmap, offset: int) -> int:
    """Find a JSON value boundary without materializing nested objects."""
    offset = _skip_json_whitespace(data, offset)
    if offset >= len(data):
        raise ValueError("missing JSON value")
    first = data[offset]
    if first == ord('"'):
        return _json_string_end(data, offset)
    if first in (ord("{"), ord("[")):
        closing = {ord("{"): ord("}"), ord("["): ord("]")}
        stack = [closing[first]]
        cursor = offset + 1
        while stack:
            if cursor >= len(data):
                raise ValueError("unterminated JSON container")
            byte = data[cursor]
            if byte == ord('"'):
                cursor = _json_string_end(data, cursor)
                continue
            if byte in closing:
                stack.append(closing[byte])
            elif byte in (ord("}"), ord("]")) and (
                not stack or byte != stack.pop()
            ):
                raise ValueError("mismatched JSON container")
            cursor += 1
        return cursor

    cursor = offset
    while cursor < len(data) and data[cursor] not in b" \t\r\n,}]":
        cursor += 1
    if cursor == offset:
        raise ValueError("invalid JSON value")
    return cursor


def _read_top_level_json_field(path: Path, field: str) -> Any:
    """Read one top-level JSON field without decoding large sibling values.

    The generated global-unique receipt may contain a very large ``counts``
    object. This scanner uses a read-only memory map to find and validate the
    top-level object boundaries, then JSON-decodes only the requested value.
    """
    with path.open("rb") as handle:
        if path.stat().st_size == 0:
            raise ValueError("empty JSON document")
        with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
            offset = _skip_json_whitespace(data, 0)
            if offset >= len(data) or data[offset] != ord("{"):
                raise ValueError("expected top-level JSON object")
            offset += 1
            found = False
            result: Any = None
            while True:
                offset = _skip_json_whitespace(data, offset)
                if offset >= len(data):
                    raise ValueError("unterminated top-level JSON object")
                if data[offset] == ord("}"):
                    offset = _skip_json_whitespace(data, offset + 1)
                    if offset != len(data):
                        raise ValueError("trailing content after JSON object")
                    return result if found else None

                key_start = offset
                key_end = _json_string_end(data, key_start)
                try:
                    key = json.loads(data[key_start:key_end].decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("invalid top-level JSON key") from exc
                offset = _skip_json_whitespace(data, key_end)
                if offset >= len(data) or data[offset] != ord(":"):
                    raise ValueError("expected colon after top-level JSON key")
                value_start = _skip_json_whitespace(data, offset + 1)
                value_end = _json_value_end(data, value_start)
                if key == field:
                    if found:
                        raise ValueError(f"duplicate top-level JSON field: {field}")
                    try:
                        result = json.loads(data[value_start:value_end].decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise ValueError(f"invalid JSON value for {field}") from exc
                    found = True

                offset = _skip_json_whitespace(data, value_end)
                if offset >= len(data):
                    raise ValueError("unterminated top-level JSON object")
                if data[offset] == ord(","):
                    offset = _skip_json_whitespace(data, offset + 1)
                    if offset >= len(data) or data[offset] != ord('"'):
                        raise ValueError("trailing comma in top-level JSON object")
                    continue
                if data[offset] == ord("}"):
                    offset = _skip_json_whitespace(data, offset + 1)
                    if offset != len(data):
                        raise ValueError("trailing content after JSON object")
                    return result if found else None
                raise ValueError("expected comma or closing brace in JSON object")


class _CompactScanRow(Mapping[str, Any]):
    """Slot-backed immutable view of the small metadata needed by a scan.

    Candidate inventories can contain hundreds of thousands of rows. A dict
    per row duplicates hash-table overhead while the values themselves remain
    shared strings from the verified catalog. Keep the same Mapping interface
    for callers, but store only the ordered values in one compact tuple.
    """

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, Any]) -> None:
        self._values = tuple(values.get(key) for key in _SCAN_ROW_KEYS)

    def __getitem__(self, key: str) -> Any:
        try:
            index = _SCAN_ROW_INDEX[key]
        except KeyError:
            raise KeyError(key) from None
        return self._values[index]

    def __iter__(self):
        return iter(_SCAN_ROW_KEYS)

    def __len__(self) -> int:
        return len(_SCAN_ROW_KEYS)


def _index_aliases(index: Mapping[str, Any]) -> tuple[str | None, dict[str, str], dict[str, str]]:
    default = index.get("release_repository_default")
    if default not in (None, CANONICAL_DATA_REPOSITORY):
        raise ValueError("foreign release_repository_default forbidden")
    aliases = index.get("run_manifest_release_tags_by_release") or {}
    if not isinstance(aliases, Mapping) or any(
        not isinstance(key, str) or not key or not isinstance(value, str) or not value
        for key, value in aliases.items()
    ):
        raise ValueError("invalid canonical RUN_MANIFEST tag mapping")
    run_ids = index.get("collection_run_ids_by_release") or {}
    if not isinstance(run_ids, Mapping) or any(
        not isinstance(key, str) or not key or not isinstance(value, str) or not value
        for key, value in run_ids.items()
    ):
        raise ValueError("invalid canonical collection run ID mapping")
    return default, dict(aliases), dict(run_ids)


def _expanded_scan_row(
    row: Mapping[str, Any],
    *,
    default_repository: str | None,
    release_tags: Mapping[str, str],
    collection_runs: Mapping[str, str],
) -> dict[str, Any]:
    value = dict(row)
    if "release_repository" not in value and default_repository == CANONICAL_DATA_REPOSITORY:
        value["release_repository"] = CANONICAL_DATA_REPOSITORY
    release_tag = str(value.get("release_tag") or "")
    canonical_tag = release_tags.get(release_tag)
    if canonical_tag is not None:
        existing = value.get("run_manifest_release_tag")
        if existing not in (None, canonical_tag):
            raise ValueError("conflicting canonical RUN_MANIFEST tag mapping")
        value["run_manifest_release_tag"] = canonical_tag
    grouped_run = collection_runs.get(release_tag)
    if grouped_run is not None:
        existing = value.get("collection_run_id")
        if existing not in (None, grouped_run):
            raise ValueError("conflicting canonical collection run ID mapping")
        value["collection_run_id"] = grouped_run
    return {key: value.get(key) for key in _SCAN_ROW_KEYS}


def _load_exact_trade_counts() -> Mapping[str, Mapping[str, Any]]:
    if not EXACT_COUNT_PATCH_PATH.is_file():
        return {}
    try:
        document = json.loads(EXACT_COUNT_PATCH_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    counts = document.get("counts") if isinstance(document, Mapping) else {}
    if not isinstance(counts, Mapping):
        return {}
    return {
        str(dataset_id): value
        for dataset_id, value in counts.items()
        if isinstance(value, Mapping)
    }


def _restore_exact_trade_count_row(
    row: dict[str, Any], counts: Mapping[str, Mapping[str, Any]],
) -> bool:
    evidence = counts.get(str(row.get("dataset_id") or ""))
    if evidence is None or evidence.get("trade_count_exact") is not True:
        return False
    row_sha = str(row.get("sha256") or "").lower()
    evidence_sha = str(evidence.get("asset_sha256") or "").lower()
    try:
        count = int(evidence.get("trade_count"))
    except (TypeError, ValueError, OverflowError):
        return False
    if len(row_sha) != 64 or row_sha != evidence_sha or count < 0:
        return False
    changed = row.get("trade_count_exact") is not True or row.get("trade_count") != count
    row["trade_count"] = count
    row["trade_count_exact"] = True
    return changed


def _iter_trade_scan_rows(index_path: Path) -> tuple[list[Mapping[str, Any]], int, list[str], int]:
    root = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(root, Mapping):
        raise ValueError("DATA_INDEX_INVALID_ROOT")
    default, release_tags, collection_runs = _index_aliases(root)
    exact_counts = _load_exact_trade_counts()
    candidates: list[dict[str, Any]] = []
    unproven: list[str] = []
    trade_shards = 0
    restored = 0
    for raw in iter_index_rows(index_path):
        row = _expanded_scan_row(
            raw,
            default_repository=default,
            release_tags=release_tags,
            collection_runs=collection_runs,
        )
        if str(row.get("family") or "").lower() not in TRADE_FAMILIES:
            continue
        trade_shards += 1
        if _restore_exact_trade_count_row(row, exact_counts):
            restored += 1
        if row.get("trade_count_exact") is not True:
            unproven.append(str(row.get("dataset_id") or ""))
        if _unique_candidate(row):
            candidates.append(_CompactScanRow(row))
    return candidates, trade_shards, sorted(unproven), restored


def _patch_index_streaming(index_path: Path, counts: Mapping[str, Mapping[str, Any]]) -> None:
    """Patch unique counts without reconstructing a multi-gigabyte logical index."""
    if index_path.is_symlink() or not index_path.is_file():
        raise ValueError("PARTITION_PARITY_UNSAFE_INDEX")
    original_root_bytes = index_path.read_bytes()
    root = json.loads(original_root_bytes)
    if not isinstance(root, dict):
        raise ValueError("DATA_INDEX_INVALID_ROOT")
    if root.get("schema") != PARTITION_SCHEMA:
        rows = root.get("shards")
        if not isinstance(rows, list):
            raise ValueError("DATA_INDEX_UNKNOWN_OR_PARTIAL_LAYOUT")
        for _ in iter_index_rows(index_path):
            pass
        for row in rows:
            patch = counts.get(str(row.get("dataset_id") or ""))
            if isinstance(patch, Mapping):
                row.update(patch)
        if index_path.read_bytes() != original_root_bytes:
            raise ValueError("PARTITION_PARITY_CONCURRENT_ROOT_CHANGE")
        _atomic_json(index_path, root)
        return

    descriptors = root.get("partitions")
    if not isinstance(descriptors, list):
        raise ValueError("PARTITION_PARITY_INVALID_METADATA")
    catalog_root = index_path.parent
    partition_directory = catalog_root / "data-index-parts"
    if partition_directory.is_symlink():
        raise ValueError("PARTITION_PARITY_UNSAFE_DIRECTORY")
    shard_count = root.get("shard_count")
    source_digest = root.get("shards_sha256")
    if (type(shard_count) is not int or shard_count < 0
            or not isinstance(source_digest, str)
            or len(source_digest) != 64
            or any(char not in "0123456789abcdef" for char in source_digest)):
        raise ValueError("PARTITION_PARITY_INVALID_METADATA")
    with tempfile.TemporaryDirectory(prefix=".global-unique-index-", dir=catalog_root) as temporary:
        stage = Path(temporary)
        new_descriptors: list[dict[str, Any]] = []
        global_digest = hashlib.sha256(b"[")
        output_digest = hashlib.sha256(b"[")
        source_count = 0
        seen_fingerprints: set[int] = set()
        reused_paths: set[str] = set()
        partition_limit = root.get("partition_max_bytes")
        if isinstance(partition_limit, bool) or not isinstance(partition_limit, int):
            raise ValueError("PARTITION_PARITY_INVALID_METADATA")
        if not 4 <= partition_limit <= 8 * 1024 * 1024:
            raise ValueError("PARTITION_PARITY_INVALID_METADATA")
        batch: list[dict[str, Any]] = []
        batch_bytes = 3

        def flush_batch() -> None:
            nonlocal batch, batch_bytes
            if not batch:
                return
            number = len(new_descriptors) + 1
            updated = _json_bytes(batch)
            if len(updated) > partition_limit:
                raise ValueError("PARTITION_PARITY_OVERSIZE")
            digest = hashlib.sha256(updated).hexdigest()
            old = descriptors[number - 1] if number <= len(descriptors) else None
            if (isinstance(old, Mapping)
                    and old.get("sha256") == digest
                    and old.get("bytes") == len(updated)
                    and old.get("row_count") == len(batch)
                    and is_canonical_partition_path(old.get("path"), number, digest)):
                relative = str(old["path"])
                reused_paths.add(relative)
            else:
                relative = immutable_partition_path(number, digest)
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(updated)
            new_descriptors.append({
                "path": relative,
                "sha256": digest,
                "bytes": len(updated),
                "row_count": len(batch),
            })
            if number > 1:
                output_digest.update(b",")
            output_digest.update(memoryview(updated)[1:-2])
            batch = []
            batch_bytes = 3

        for number, descriptor in enumerate(descriptors, 1):
            if not isinstance(descriptor, Mapping):
                raise ValueError("PARTITION_PARITY_INVALID_DESCRIPTOR")
            relative = descriptor.get("path")
            expected_size = descriptor.get("bytes")
            expected_rows = descriptor.get("row_count")
            expected_sha = descriptor.get("sha256")
            if not is_canonical_partition_path(relative, number, expected_sha):
                raise ValueError("PARTITION_PARITY_NONCANONICAL_SEQUENCE")
            if (type(expected_size) is not int or not 0 < expected_size <= partition_limit
                    or type(expected_rows) is not int or expected_rows <= 0
                    or not isinstance(expected_sha, str) or len(expected_sha) != 64
                    or any(char not in "0123456789abcdef" for char in expected_sha)):
                raise ValueError("PARTITION_PARITY_INVALID_DESCRIPTOR")
            source = catalog_root / relative
            if source.is_symlink() or not source.is_file():
                raise ValueError("PARTITION_PARITY_MISSING_FILE")
            data = source.read_bytes()
            if len(data) != expected_size or len(data) > partition_limit:
                raise ValueError("PARTITION_PARITY_SIZE_MISMATCH")
            if hashlib.sha256(data).hexdigest() != expected_sha:
                raise ValueError("PARTITION_PARITY_DIGEST_MISMATCH")
            if not data.startswith(b"[") or not data.endswith(b"]\n"):
                raise ValueError("PARTITION_PARITY_GLOBAL_MISMATCH")
            part_rows = json.loads(data)
            if not isinstance(part_rows, list) or not part_rows or len(part_rows) != expected_rows:
                raise ValueError("PARTITION_PARITY_INVALID_ROWS")
            if source_count:
                global_digest.update(b",")
            global_digest.update(memoryview(data)[1:-2])
            for row in part_rows:
                if not isinstance(row, dict):
                    raise ValueError("PARTITION_PARITY_INVALID_ROW")
                dataset_id = row.get("dataset_id")
                if not isinstance(dataset_id, str) or not dataset_id:
                    raise ValueError("PARTITION_PARITY_DUPLICATE_OR_MISSING_DATASET_ID")
                fingerprint = _dataset_id_fingerprint(dataset_id)
                if fingerprint in seen_fingerprints:
                    raise ValueError("PARTITION_PARITY_DUPLICATE_OR_MISSING_DATASET_ID")
                seen_fingerprints.add(fingerprint)
                source_count += 1
                patch = counts.get(str(row.get("dataset_id") or ""))
                if isinstance(patch, Mapping):
                    row.update(patch)
                encoded_len = len(_json_bytes(row)) - 1
                if batch and batch_bytes + encoded_len + 1 > partition_limit:
                    flush_batch()
                if 3 + encoded_len > partition_limit:
                    raise ValueError("PARTITION_PARITY_SINGLE_ROW_OVERSIZE")
                batch.append(row)
                batch_bytes += encoded_len + (1 if len(batch) > 1 else 0)
        flush_batch()
        global_digest.update(b"]\n")
        output_digest.update(b"]\n")
        if source_count != shard_count or global_digest.hexdigest() != source_digest:
            raise ValueError("PARTITION_PARITY_GLOBAL_MISMATCH")
        root["partitions"] = new_descriptors
        root["shards_sha256"] = output_digest.hexdigest()
        staged_root = stage / "DATA_INDEX.json"
        staged_root.write_bytes(_json_bytes(root))
        observed = 0
        for _ in iter_index_rows(staged_root):
            observed += 1
        if observed != shard_count:
            raise ValueError("PARTITION_PARITY_COUNT_MISMATCH")

        partition_directory.mkdir(parents=True, exist_ok=True)
        for descriptor in new_descriptors:
            relative = descriptor["path"]
            destination = catalog_root / relative
            if relative in reused_paths:
                if destination.is_symlink() or not destination.is_file():
                    raise ValueError("PARTITION_PARITY_MISSING_FILE")
                continue
            content = (stage / relative).read_bytes()
            _publish_immutable_partition(destination, content)

        descriptor_fd, temporary_name = tempfile.mkstemp(
            prefix=f".{index_path.name}.", suffix=".publish.tmp", dir=catalog_root,
        )
        temporary_root = Path(temporary_name)
        try:
            with os.fdopen(descriptor_fd, "wb") as handle:
                handle.write(staged_root.read_bytes())
                handle.flush()
                os.fsync(handle.fileno())
            if json.loads(temporary_root.read_bytes()) != root:
                raise ValueError("PARTITION_PARITY_STAGED_WRITE_MISMATCH")
            if index_path.read_bytes() != original_root_bytes:
                raise ValueError("PARTITION_PARITY_CONCURRENT_ROOT_CHANGE")
            os.replace(temporary_root, index_path)
        finally:
            temporary_root.unlink(missing_ok=True)


def _open_checkpoint(path: Path, candidates: list[Mapping[str, Any]]) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(path, timeout=0)
    database.execute("PRAGMA journal_mode=WAL")
    database.execute("PRAGMA synchronous=FULL")
    database.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    database.execute("CREATE TABLE IF NOT EXISTS ids (identity TEXT PRIMARY KEY)")
    database.execute("""CREATE TABLE IF NOT EXISTS completed (
        dataset_id TEXT PRIMARY KEY, asset_sha256 TEXT NOT NULL,
        trade_count INTEGER NOT NULL, unique_count INTEGER NOT NULL,
        global_new INTEGER NOT NULL)""")
    version = database.execute("SELECT value FROM metadata WHERE key='identity_version'").fetchone()
    if version is None:
        if database.execute("SELECT COUNT(*) FROM completed").fetchone()[0] or database.execute("SELECT COUNT(*) FROM ids").fetchone()[0]:
            raise ValueError("checkpoint has identities without a version")
        database.execute("INSERT INTO metadata VALUES ('identity_version', ?)", (IDENTITY_VERSION,))
        database.commit()
    elif version[0] != IDENTITY_VERSION:
        raise ValueError("checkpoint identity version mismatch")
    merge_order = database.execute(
        "SELECT value FROM metadata WHERE key='merge_order_version'"
    ).fetchone()
    if merge_order is None:
        if database.execute("SELECT COUNT(*) FROM completed").fetchone()[0] or database.execute(
            "SELECT COUNT(*) FROM ids"
        ).fetchone()[0]:
            database.close()
            raise ValueError(
                "checkpoint merge order is unverified; preserve it and rebuild "
                "the unique-count checkpoint before publishing per-shard attribution"
            )
        database.execute(
            "INSERT INTO metadata VALUES ('merge_order_version', ?)",
            (MERGE_ORDER_VERSION,),
        )
        database.commit()
    elif merge_order[0] != MERGE_ORDER_VERSION:
        database.close()
        raise ValueError("checkpoint merge order version mismatch")
    if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("checkpoint integrity check failed")
    # Sort the compact inventory in place, then validate checkpoint provenance
    # with a merge walk. Keep only the inventory and one SQLite row in memory;
    # materializing candidate IDs and all completed rows duplicates a large
    # amount of data on every resume.
    candidates.sort(key=lambda row: str(row.get("dataset_id") or ""))
    previous_id = ""
    for row in candidates:
        dataset_id = str(row.get("dataset_id") or "")
        if not dataset_id or dataset_id == previous_id:
            raise ValueError("duplicate or empty candidate dataset_id")
        previous_id = dataset_id

    completed_identity_count = 0
    completed = database.execute(
        "SELECT dataset_id, asset_sha256, trade_count, unique_count, global_new "
        "FROM completed ORDER BY dataset_id"
    )
    candidate_index = 0
    for dataset_id, sha, trades, unique, new in completed:
        while (candidate_index < len(candidates)
               and str(candidates[candidate_index].get("dataset_id") or "") < dataset_id):
            candidate_index += 1
        if (candidate_index >= len(candidates)
                or str(candidates[candidate_index].get("dataset_id") or "") != dataset_id):
            raise ValueError("checkpoint shard provenance mismatch")
        row = candidates[candidate_index]
        if (str(row.get("sha256") or "").lower() != sha
                or row.get("trade_count_exact") is not True or row.get("trade_count") != trades
                or not 0 <= new <= unique <= trades):
            raise ValueError("checkpoint shard provenance mismatch")
        completed_identity_count += new
    if database.execute("SELECT COUNT(*) FROM ids").fetchone()[0] != completed_identity_count:
        raise ValueError("checkpoint identity count mismatch")
    return database


def _pending_scan_candidates(
    candidates: list[Mapping[str, Any]],
    database: sqlite3.Connection,
    limit: int,
) -> list[Mapping[str, Any]]:
    """Select the next unfinished shards using an ordered merge, not a set."""
    pending: list[Mapping[str, Any]] = []
    completed = iter(database.execute("SELECT dataset_id FROM completed ORDER BY dataset_id"))
    next_completed = next(completed, None)
    for row in candidates:
        dataset_id = str(row.get("dataset_id") or "")
        while next_completed is not None and next_completed[0] < dataset_id:
            next_completed = next(completed, None)
        if next_completed is not None and next_completed[0] == dataset_id:
            next_completed = next(completed, None)
            continue
        pending.append(row)
        if len(pending) >= limit:
            break
    return pending


def _merge_checkpoint_shard(
    database: sqlite3.Connection,
    row: Mapping[str, Any],
    scanned: Mapping[str, Any],
    *,
    manage_transaction: bool = True,
) -> None:
    if (scanned.get("exact") is not True or type(scanned.get("trade_count_scanned")) is not int
            or scanned["trade_count_scanned"] != row.get("trade_count")
            or type(scanned.get("unique_trade_count")) is not int):
        raise ValueError("shard exact trade count mismatch")
    dataset_id = str(row.get("dataset_id") or "")
    identity_path = Path(str(scanned["identity_path"]))
    savepoint = "merge_checkpoint_shard"
    try:
        if manage_transaction:
            database.execute("BEGIN IMMEDIATE")
        else:
            database.execute(f"SAVEPOINT {savepoint}")
        if database.execute("SELECT 1 FROM completed WHERE dataset_id=?", (dataset_id,)).fetchone():
            raise ValueError("shard already checkpointed")
        global_new = 0
        local_count = 0
        previous_identity: str | None = None
        identity_batch: list[tuple[str]] = []

        def flush_identity_batch() -> None:
            nonlocal global_new
            if not identity_batch:
                return
            before = database.total_changes
            database.executemany(
                "INSERT OR IGNORE INTO ids(identity) VALUES (?)",
                identity_batch,
            )
            global_new += database.total_changes - before
            identity_batch.clear()

        with identity_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                identity = canonical_identity(line.rstrip("\n"))
                if previous_identity is not None and identity <= previous_identity:
                    raise ValueError("shard identity file is not strictly sorted and unique")
                previous_identity = identity
                local_count += 1
                identity_batch.append((identity,))
                if len(identity_batch) >= IDENTITY_INSERT_BATCH_SIZE:
                    flush_identity_batch()
        flush_identity_batch()
        if local_count != scanned["unique_trade_count"]:
            raise ValueError("shard unique identity count mismatch")
        database.execute(
            "INSERT INTO completed VALUES (?, ?, ?, ?, ?)",
            (dataset_id, str(row["sha256"]).lower(), scanned["trade_count_scanned"], local_count, global_new),
        )
        if manage_transaction:
            database.commit()
        else:
            database.execute(f"RELEASE SAVEPOINT {savepoint}")
    except BaseException:
        if manage_transaction:
            database.rollback()
        else:
            database.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            database.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise


def _persist_manifest_unique_counts(
    row: Mapping[str, Any],
    *,
    unique_count: int,
    exact: bool,
) -> None:
    manifest_path = (ROOT / str(row.get("manifest_path") or "")).resolve()
    if not manifest_path.is_relative_to(ROOT.resolve()) or not manifest_path.is_file():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(manifest, dict):
        return
    manifest["unique_trade_count"] = int(unique_count) if exact else None
    manifest["unique_trade_count_exact"] = bool(exact)
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, manifest_path)


def _restore_exact_trade_count_rows(
    rows: list[Any],
    *,
    patch_path: Path | None = None,
) -> int:
    """Rehydrate SHA-matched exact trade counts before selecting unique-scan candidates.

    Replay qualification is a separate concern and must never be able to shrink
    the globally deduplicated trade universe by temporarily clearing
    trade_count_exact in DATA_INDEX.
    """
    path=patch_path or EXACT_COUNT_PATCH_PATH
    if not path.is_file():
        return 0
    try:
        doc=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError,TypeError):
        return 0
    counts=doc.get("counts") if isinstance(doc,Mapping) else {}
    if not isinstance(counts,Mapping):
        return 0

    restored=0
    for row in rows:
        if not isinstance(row,dict):
            continue
        dataset_id=str(row.get("dataset_id") or "")
        family=str(row.get("family") or "").lower()
        if not dataset_id or family not in TRADE_FAMILIES:
            continue
        evidence=counts.get(dataset_id)
        if not isinstance(evidence,Mapping) or evidence.get("trade_count_exact") is not True:
            continue
        row_sha=str(row.get("sha256") or "").lower()
        evidence_sha=str(evidence.get("asset_sha256") or "").lower()
        if len(row_sha)!=64 or evidence_sha!=row_sha:
            continue
        try:
            count=int(evidence.get("trade_count"))
        except (TypeError,ValueError,OverflowError):
            continue
        if count<0:
            continue
        if row.get("trade_count_exact") is not True or row.get("trade_count")!=count:
            restored+=1
        row["trade_count"]=count
        row["trade_count_exact"]=True
    return restored


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0 else None


def _unique_candidate(row: Mapping[str, Any]) -> bool:
    """Return True only for immutable shards that actually carry trades."""
    dataset_id = str(row.get("dataset_id") or "")
    family = str(row.get("family") or "").lower()
    if not dataset_id or family not in TRADE_FAMILIES:
        return False
    if row.get("trade_count_exact") is not True:
        return False
    if _positive_int(row.get("trade_count")) is None:
        return False
    return bool(
        row.get("release_repository")
        and row.get("release_tag")
        and row.get("release_asset")
        and row.get("sha256")
        and row.get("bytes")
    )


def canonical_identity(value: str) -> str:
    """Use the complete canonical identity; hashes are evidence digests only."""
    if not isinstance(value, str) or not value:
        raise ValueError("empty trade identity")
    return value


def _scan_candidate(row: Mapping[str, Any], temporary_root: Path) -> dict[str, Any]:
    """Download one immutable trade shard and persist only its local identity set."""
    dataset_id = str(row.get("dataset_id") or "")
    if (
        not dataset_id
        or "/" in dataset_id
        or "\\" in dataset_id
        or Path(dataset_id).is_absolute()
    ):
        raise ValueError("dataset_id escapes temporary scan root")
    # Dataset IDs are also release asset names and can be very long.  Repeating
    # that identifier in ``temporary_root / dataset_id / asset`` exceeds the
    # Windows path limit for otherwise valid Release assets.  A deterministic
    # digest keeps workspace isolation and collision resistance without putting
    # untrusted or oversized names into the filesystem path.
    workspace_name = hashlib.sha256(dataset_id.encode("utf-8")).hexdigest()[:24]
    shard_root = (temporary_root / workspace_name).resolve()
    if not shard_root.is_relative_to(temporary_root.resolve()):
        raise ValueError("dataset_id escapes temporary scan root")
    shard_root.mkdir(parents=True, exist_ok=True)
    asset = _download(row, shard_root)
    total = 0
    exact = True
    shard_ids: set[str] = set()
    with gzip.open(asset, "rb") as handle:
        while line := handle.readline(MAX_JSONL_RECORD_BYTES + 1):
            if len(line) > MAX_JSONL_RECORD_BYTES:
                raise ValueError("oversized JSONL record")
            raw = json.loads(line)
            if not isinstance(raw, Mapping):
                raise ValueError("non-object JSONL record")
            keys = _native_trade_keys(
                raw,
                venue=str(row.get("venue") or "unknown"),
                family=str(row.get("family") or ""),
                symbol=str(row.get("symbol") or ""),
            )
            if keys is None:
                exact = False
                continue
            total += len(keys)
            shard_ids.update(canonical_identity(key) for key in keys)

    identity_path = shard_root / "identities.txt"
    if exact:
        with identity_path.open("w", encoding="utf-8", newline="\n") as handle:
            for identity in sorted(shard_ids):
                handle.write(identity)
                handle.write("\n")

    # The downloaded release asset is no longer needed after deterministic parsing.
    if asset.resolve().is_relative_to(temporary_root.resolve()):
        with contextlib.suppress(OSError):
            asset.unlink()

    return {
        "dataset_id": dataset_id,
        "trade_count_scanned": total,
        "unique_trade_count": len(shard_ids),
        "identity_path": str(identity_path),
        "exact": exact,
    }


def _digest_sqlite_identities(database: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for (identity,) in database.execute("SELECT identity FROM ids ORDER BY identity"):
        digest.update(str(identity).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _write_global_unique_patch(path: Path, payload: Mapping[str, Any]) -> None:
    """Durably publish the compact receipt without exposing a truncated patch."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if temporary.stat().st_size >= GLOBAL_UNIQUE_PATCH_MAX_BYTES:
            raise ValueError("GLOBAL_UNIQUE_PATCH_NEEDS_PARTITION")
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    if args.limit < 1:
        raise SystemExit("limit must be positive")
    if not 1 <= args.workers <= 32:
        raise SystemExit("workers must be between 1 and 32")

    all_candidates, trade_shards_in_scope, unproven_trade_count_ids, restored_exact_trade_rows = (
        _iter_trade_scan_rows(INDEX_PATH)
    )

    failure_attempts: dict[str, Any] = {}
    previous_attempts: Any = None
    if PATCH_PATH.exists():
        try:
            previous_attempts = _read_top_level_json_field(
                PATCH_PATH,
                "failure_attempts",
            )
        except (OSError, ValueError, TypeError):
            previous_attempts = None
    if isinstance(previous_attempts, dict):
        failure_attempts = previous_attempts

    database = _open_checkpoint(CHECKPOINT_PATH, all_candidates)
    already_done_count = int(
        database.execute("SELECT COUNT(*) FROM completed").fetchone()[0]
    )
    candidates = _pending_scan_candidates(all_candidates, database, args.limit)
    failed: list[dict[str, Any]] = []
    failure_reasons: dict[str, dict[str, Any]] = {}
    counts: dict[str, dict[str, Any]] = {}
    attempted_count = 0
    checkpoint_transaction_open = False
    checkpoint_batch_successes = 0

    # Windows can retain a decompressed asset handle briefly after a worker
    # finishes.  Cleanup must never discard an otherwise durable checkpoint or
    # hide the final receipt behind WinError 145; stale temporary files remain
    # outside the SAFE/index paths and are cleaned on a later run.
    with tempfile.TemporaryDirectory(
        prefix="alina-global-unique-",
        ignore_cleanup_errors=True,
    ) as temporary:
        root = Path(temporary)

        def scan(row: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
            result = _scan_candidate(row, root)
            return str(row.get("dataset_id") or ""), result

        def record(row: Mapping[str, Any], scanned: dict[str, Any] | Exception | None) -> bool:
            nonlocal checkpoint_transaction_open, checkpoint_batch_successes, attempted_count
            attempted_count += 1
            dataset_id = str(row.get("dataset_id") or "")
            if isinstance(scanned, Exception) or scanned is None:
                exc = scanned if isinstance(scanned, Exception) else RuntimeError("missing_scan_result")
                attempts = int(failure_attempts.get(dataset_id) or 0) + 1
                failure_attempts[dataset_id] = attempts
                failure = {
                    "dataset_id": dataset_id,
                    "reason": type(exc).__name__,
                    "detail": str(exc)[-500:],
                    "attempts": attempts,
                }
                failed.append(failure)
                failure_reasons[dataset_id] = failure
                return False
            if scanned.get("exact") is not True:
                attempts = int(failure_attempts.get(dataset_id) or 0) + 1
                failure_attempts[dataset_id] = attempts
                failure = {
                    "dataset_id": dataset_id,
                    "reason": "identity_missing",
                    "attempts": attempts,
                }
                failed.append(failure)
                failure_reasons[dataset_id] = failure
                return False

            try:
                if not checkpoint_transaction_open:
                    database.execute("BEGIN IMMEDIATE")
                    checkpoint_transaction_open = True
                _merge_checkpoint_shard(
                    database,
                    row,
                    scanned,
                    manage_transaction=False,
                )
            except (OSError, ValueError, sqlite3.Error) as exc:
                attempts = int(failure_attempts.get(dataset_id) or 0) + 1
                failure_attempts[dataset_id] = attempts
                failure = {
                    "dataset_id": dataset_id,
                    "reason": type(exc).__name__,
                    "detail": str(exc)[-500:],
                    "attempts": attempts,
                }
                failed.append(failure)
                failure_reasons[dataset_id] = failure
                return False
            checkpoint_batch_successes += 1
            if checkpoint_batch_successes >= CHECKPOINT_COMMIT_INTERVAL:
                database.commit()
                checkpoint_transaction_open = False
                checkpoint_batch_successes = 0
            _persist_manifest_unique_counts(
                row,
                unique_count=scanned["unique_trade_count"],
                exact=True,
            )
            failure_attempts.pop(dataset_id, None)
            return True

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            # Keep the number of simultaneous decompressions bounded.  A large
            # release shard can legitimately contain many identities; queuing
            # every candidate at once made the old implementation retain several
            # gigabytes before the first checkpoint merge.
            pending: dict[Any, tuple[int, Mapping[str, Any], int]] = {}
            ready: dict[int, tuple[Mapping[str, Any], dict[str, Any] | Exception]] = {}
            next_submit = 0
            next_record = 0
            in_flight_bytes = 0
            stop_after_failure = False

            def submit_next() -> bool:
                nonlocal next_submit, in_flight_bytes
                if next_submit >= len(candidates):
                    return False
                row = candidates[next_submit]
                row_bytes = max(1, int(row.get("bytes") or 0))
                if pending and in_flight_bytes + row_bytes > MAX_IN_FLIGHT_RELEASE_BYTES:
                    return False
                pending[pool.submit(scan, row)] = (next_submit, row, row_bytes)
                next_submit += 1
                in_flight_bytes += row_bytes
                return True

            while True:
                while not stop_after_failure and len(pending) < args.workers and submit_next():
                    pass
                if not pending:
                    break
                completed_futures, _ = wait(
                    tuple(pending),
                    return_when=FIRST_COMPLETED,
                )
                for future in completed_futures:
                    candidate_number, row, row_bytes = pending.pop(future)
                    in_flight_bytes -= row_bytes
                    scanned: dict[str, Any] | Exception
                    try:
                        _, scanned = future.result()
                    except Exception as exc:  # isolated shard failure; coverage stays false
                        scanned = exc
                    ready[candidate_number] = (row, scanned)

                while next_record in ready:
                    row, scanned = ready.pop(next_record)
                    next_record += 1
                    if not record(row, scanned):
                        stop_after_failure = True
                        for future in pending:
                            future.cancel()
                        pending.clear()
                        break
                if stop_after_failure:
                    break


    if checkpoint_transaction_open:
        database.commit()
    counts = {}
    for dataset_id, sha, trades, unique, global_new in database.execute(
        "SELECT dataset_id, asset_sha256, trade_count, unique_count, global_new FROM completed"
    ):
        counts[dataset_id] = {
            "asset_sha256": sha, "trade_count_scanned": trades,
            "unique_trade_count": unique, "unique_trade_count_exact": True,
            "global_new_identity_count": global_new,
            "cross_shard_overlap_count": unique - global_new,
            "identity_version": IDENTITY_VERSION,
        }
    observed_global_count = int(database.execute("SELECT COUNT(*) FROM ids").fetchone()[0])
    observed_identity_digest = _digest_sqlite_identities(database)
    database.close()

    _patch_index_streaming(INDEX_PATH, counts)

    remaining_ids = [
        str(row.get("dataset_id") or "")
        for row in all_candidates
        if str(row.get("dataset_id") or "") not in counts
    ]
    unscanned_count = max(
        0,
        len(all_candidates) - already_done_count - attempted_count,
    )
    coverage_complete = (
        not unproven_trade_count_ids
        and not remaining_ids
        and not failed
        and unscanned_count == 0
    )
    cross_shard_overlap_count = sum(
        int(value.get("cross_shard_overlap_count") or 0)
        for value in counts.values()
        if isinstance(value, Mapping)
    )

    result = {
        "schema": GLOBAL_UNIQUE_PATCH_SCHEMA,
        "method": "bounded_trade_corpus_scan_with_durable_sqlite_checkpoint",
        "identity_version": IDENTITY_VERSION,
        "merge_order_version": MERGE_ORDER_VERSION,
        "collision_policy": (
            "full canonical identity strings; native identifiers preferred; "
            "ambiguous missing identities fail closed"
        ),
        "trade_shards_in_scope": trade_shards_in_scope,
        "unproven_trade_count_shards": len(unproven_trade_count_ids),
        "unproven_trade_count_dataset_ids": unproven_trade_count_ids,
        "candidate_trade_shards": len(all_candidates),
        "restored_exact_trade_rows": restored_exact_trade_rows,
        "selected_for_attempt": len(candidates),
        "attempted": attempted_count,
        "successful": len(counts),
        "failed": failed,
        "failure_reasons": dict(sorted(failure_reasons.items())),
        "failure_attempts": dict(sorted(failure_attempts.items())),
        "counts": compact_global_unique_count_rows(
            counts,
            identity_version=IDENTITY_VERSION,
        ),
        "remaining_candidate_shards": len(remaining_ids),
        "unscanned_candidate_shards": unscanned_count,
        "observed_unique_trade_count": observed_global_count,
        "global_unique_trade_count": (
            observed_global_count if coverage_complete else None
        ),
        "observed_identity_digest": observed_identity_digest,
        "global_identity_digest": (
            observed_identity_digest if coverage_complete else None
        ),
        "cross_shard_overlap_count": cross_shard_overlap_count,
        "coverage_complete": coverage_complete,
        "identity_store_persisted": True,
        "identity_store_policy": (
            "identity universe is checkpointed under runtime/reports with SQLite integrity and SHA-bound shards; "
            "only compact counts and digest are published in Git"
        ),
    }
    _write_global_unique_patch(PATCH_PATH, result)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "trade_shards_in_scope",
                    "unproven_trade_count_shards",
                    "candidate_trade_shards",
                    "restored_exact_trade_rows",
                    "attempted",
                    "successful",
                    "remaining_candidate_shards",
                    "global_unique_trade_count",
                    "coverage_complete",
                )
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
