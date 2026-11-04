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
except ModuleNotFoundError:
    from backfill_exact_trade_counts import TRADE_FAMILIES, _download, _native_trade_keys

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
    from tools.partitioned_data_index import _json_bytes, iter_index_rows
except ModuleNotFoundError:
    from partitioned_data_index import SCHEMA as PARTITION_SCHEMA
    from partitioned_data_index import _json_bytes, iter_index_rows

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "catalog" / "DATA_INDEX.json"
PATCH_PATH = ROOT / "catalog" / "TRADE_UNIQUE_COUNT_PATCH.json"
EXACT_COUNT_PATCH_PATH = ROOT / "catalog" / "TRADE_COUNT_PATCH.json"
CHECKPOINT_PATH = ROOT / "runtime" / "reports" / "global-unique-trades" / "identities.sqlite"
IDENTITY_VERSION = "native-id-or-venue-family-symbol-time-side-price-size-v3-full-string"
MAX_IN_FLIGHT_RELEASE_BYTES = 768 * 1024 * 1024
CHECKPOINT_COMMIT_INTERVAL = 32
_SCAN_ROW_KEYS = (
    "dataset_id", "family", "venue", "symbol", "trade_count",
    "trade_count_exact", "manifest_path", "release_repository",
    "release_tag", "release_asset", "release_container_asset",
    "release_member", "release_storage", "release_remote_size",
    "release_remote_digest", "sha256", "bytes",
)


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


def _iter_trade_scan_rows(index_path: Path) -> tuple[list[dict[str, Any]], int, list[str], int]:
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
            candidates.append(row)
    return candidates, trade_shards, sorted(unproven), restored


def _patch_index_streaming(index_path: Path, counts: Mapping[str, Mapping[str, Any]]) -> None:
    """Patch unique counts without reconstructing a multi-gigabyte logical index."""
    root = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(root, dict):
        raise ValueError("DATA_INDEX_INVALID_ROOT")
    if root.get("schema") != PARTITION_SCHEMA:
        rows = root.get("shards")
        if not isinstance(rows, list):
            raise ValueError("DATA_INDEX_UNKNOWN_OR_PARTIAL_LAYOUT")
        for row in rows:
            patch = counts.get(str(row.get("dataset_id") or ""))
            if isinstance(patch, Mapping):
                row.update(patch)
        _atomic_json(index_path, root)
        return

    descriptors = root.get("partitions")
    if not isinstance(descriptors, list):
        raise ValueError("PARTITION_PARITY_INVALID_METADATA")
    catalog_root = index_path.parent
    with tempfile.TemporaryDirectory(prefix=".global-unique-index-", dir=catalog_root) as temporary:
        stage = Path(temporary)
        stage_parts = stage / "data-index-parts"
        stage_parts.mkdir()
        new_descriptors: list[dict[str, Any]] = []
        global_digest = hashlib.sha256(b"[")
        partition_limit = root.get("partition_max_bytes")
        if isinstance(partition_limit, bool) or not isinstance(partition_limit, int):
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
            destination = stage_parts / f"part-{number:06d}.json"
            destination.write_bytes(updated)
            new_descriptors.append({
                "path": f"data-index-parts/part-{number:06d}.json",
                "sha256": hashlib.sha256(updated).hexdigest(),
                "bytes": len(updated),
                "row_count": len(batch),
            })
            if number > 1:
                global_digest.update(b",")
            global_digest.update(memoryview(updated)[1:-2])
            batch = []
            batch_bytes = 3

        for number, descriptor in enumerate(descriptors, 1):
            if not isinstance(descriptor, Mapping):
                raise ValueError("PARTITION_PARITY_INVALID_DESCRIPTOR")
            relative = f"data-index-parts/part-{number:06d}.json"
            if descriptor.get("path") != relative:
                raise ValueError("PARTITION_PARITY_NONCANONICAL_SEQUENCE")
            source = catalog_root / relative
            data = source.read_bytes()
            part_rows = json.loads(data)
            if not isinstance(part_rows, list):
                raise ValueError("PARTITION_PARITY_INVALID_ROWS")
            for row in part_rows:
                if not isinstance(row, dict):
                    raise ValueError("PARTITION_PARITY_INVALID_ROW")
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
        root["partitions"] = new_descriptors
        global_digest.update(b"]\n")
        root["shards_sha256"] = global_digest.hexdigest()
        staged_root = stage / "DATA_INDEX.json"
        staged_root.write_bytes(_json_bytes(root))
        observed = 0
        for _ in iter_index_rows(staged_root):
            observed += 1
        if observed != root.get("shard_count"):
            raise ValueError("PARTITION_PARITY_COUNT_MISMATCH")

        live_parts = catalog_root / "data-index-parts"
        for number in range(1, len(new_descriptors) + 1):
            live = live_parts / f"part-{number:06d}.json"
            temporary_part = live.with_suffix(".publish.tmp")
            temporary_part.write_bytes((stage_parts / live.name).read_bytes())
            os.replace(temporary_part, live)
        temporary_root = index_path.with_suffix(index_path.suffix + ".publish.tmp")
        temporary_root.write_bytes(staged_root.read_bytes())
        os.replace(temporary_root, index_path)


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
    if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("checkpoint integrity check failed")
    expected = {str(row.get("dataset_id") or ""): row for row in candidates}
    if len(expected) != len(candidates) or not all(expected):
        raise ValueError("duplicate or empty candidate dataset_id")
    completed = database.execute("SELECT dataset_id, asset_sha256, trade_count, unique_count, global_new FROM completed").fetchall()
    for dataset_id, sha, trades, unique, new in completed:
        row = expected.get(dataset_id)
        if (row is None or str(row.get("sha256") or "").lower() != sha
                or row.get("trade_count_exact") is not True or row.get("trade_count") != trades
                or not 0 <= new <= unique <= trades):
            raise ValueError("checkpoint shard provenance mismatch")
    if database.execute("SELECT COUNT(*) FROM ids").fetchone()[0] != sum(item[4] for item in completed):
        raise ValueError("checkpoint identity count mismatch")
    return database


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
        with identity_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                identity = canonical_identity(line.rstrip("\n"))
                if previous_identity is not None and identity <= previous_identity:
                    raise ValueError("shard identity file is not strictly sorted and unique")
                previous_identity = identity
                local_count += 1
                before = database.total_changes
                database.execute("INSERT OR IGNORE INTO ids(identity) VALUES (?)", (identity,))
                global_new += int(database.total_changes > before)
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
    with gzip.open(asset, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            if not isinstance(raw, Mapping):
                continue
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

    prior: dict[str, Any] = {}
    if PATCH_PATH.exists():
        try:
            prior = json.loads(PATCH_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            prior = {}
    failure_attempts = (
        prior.get("failure_attempts")
        if isinstance(prior, dict) and isinstance(prior.get("failure_attempts"), dict)
        else {}
    )

    all_candidates = sorted(all_candidates, key=lambda row: str(row.get("dataset_id") or ""))
    database = _open_checkpoint(CHECKPOINT_PATH, all_candidates)
    already_done = {row[0] for row in database.execute("SELECT dataset_id FROM completed")}
    candidates = [row for row in all_candidates if str(row.get("dataset_id") or "") not in already_done][: args.limit]
    failed: list[dict[str, Any]] = []
    failure_reasons: dict[str, dict[str, Any]] = {}
    counts: dict[str, dict[str, Any]] = {}
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

        def record(row: Mapping[str, Any], scanned: dict[str, Any] | Exception | None) -> None:
            nonlocal checkpoint_transaction_open, checkpoint_batch_successes
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
                return
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
                return

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
                return
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

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            # Keep the number of simultaneous decompressions bounded.  A large
            # release shard can legitimately contain many identities; queuing
            # every candidate at once made the old implementation retain several
            # gigabytes before the first checkpoint merge.
            pending: dict[Any, tuple[Mapping[str, Any], int]] = {}
            candidate_iter = iter(candidates)
            in_flight_bytes = 0
            buffered: Mapping[str, Any] | None = None

            def submit_next() -> bool:
                nonlocal buffered, in_flight_bytes
                if buffered is None:
                    try:
                        buffered = next(candidate_iter)
                    except StopIteration:
                        return False
                row = buffered
                row_bytes = max(1, int(row.get("bytes") or 0))
                if pending and in_flight_bytes + row_bytes > MAX_IN_FLIGHT_RELEASE_BYTES:
                    return False
                pending[pool.submit(scan, row)] = (row, row_bytes)
                in_flight_bytes += row_bytes
                buffered = None
                return True

            while True:
                while len(pending) < args.workers and submit_next():
                    pass
                if not pending:
                    break
                completed_futures, _ = wait(
                    tuple(pending),
                    return_when=FIRST_COMPLETED,
                )
                for future in completed_futures:
                    row, row_bytes = pending.pop(future)
                    in_flight_bytes -= row_bytes
                    scanned: dict[str, Any] | Exception
                    try:
                        _, scanned = future.result()
                    except Exception as exc:  # isolated shard failure; coverage stays false
                        scanned = exc
                    record(row, scanned)


    if checkpoint_transaction_open:
        database.commit()
    completed = database.execute("SELECT dataset_id, asset_sha256, trade_count, unique_count, global_new FROM completed").fetchall()
    counts = {
        dataset_id: {
            "asset_sha256": sha, "trade_count_scanned": trades,
            "unique_trade_count": unique, "unique_trade_count_exact": True,
            "global_new_identity_count": global_new,
            "cross_shard_overlap_count": unique - global_new,
            "identity_version": IDENTITY_VERSION,
        }
        for dataset_id, sha, trades, unique, global_new in completed
    }
    successful_ids = set(counts)
    observed_global_count = int(database.execute("SELECT COUNT(*) FROM ids").fetchone()[0])
    observed_identity_digest = _digest_sqlite_identities(database)
    database.close()

    _patch_index_streaming(INDEX_PATH, counts)

    all_candidate_ids = {
        str(row.get("dataset_id") or "") for row in all_candidates
    }
    remaining_ids = sorted(all_candidate_ids - successful_ids)
    unscanned_count = max(0, len(all_candidates) - len(already_done) - len(candidates))
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
        "schema": "alina.global_unique_trade_patch.v4",
        "method": "bounded_trade_corpus_scan_with_durable_sqlite_checkpoint",
        "identity_version": IDENTITY_VERSION,
        "collision_policy": (
            "full canonical identity strings; native identifiers preferred; "
            "ambiguous missing identities fail closed"
        ),
        "trade_shards_in_scope": trade_shards_in_scope,
        "unproven_trade_count_shards": len(unproven_trade_count_ids),
        "unproven_trade_count_dataset_ids": unproven_trade_count_ids,
        "candidate_trade_shards": len(all_candidates),
        "restored_exact_trade_rows": restored_exact_trade_rows,
        "attempted": len(candidates),
        "successful": len(successful_ids),
        "failed": failed,
        "failure_reasons": dict(sorted(failure_reasons.items())),
        "failure_attempts": dict(sorted(failure_attempts.items())),
        "counts": dict(sorted(counts.items())),
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
    PATCH_PATH.write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
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
