#!/usr/bin/env python3
"""Measure exact uncompressed sizes and generic record counts for release assets."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.backfill_exact_trade_counts import _download
except ModuleNotFoundError:
    from backfill_exact_trade_counts import _download

try:
    from tools.index_run_manifest import hydrate_default_release_repository
except ModuleNotFoundError:
    from index_run_manifest import hydrate_default_release_repository

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "catalog" / "DATA_INDEX.json"
SIZE_PATCH = ROOT / "catalog" / "UNCOMPRESSED_SIZE_PATCH.json"
RECORD_PATCH = ROOT / "catalog" / "RECORD_COUNT_PATCH.json"


def _measure_candidate(
    row: Mapping[str, Any], temporary_root: str
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    dataset_id = str(row["dataset_id"])
    target = Path(temporary_root) / hashlib.sha256(dataset_id.encode("utf-8")).hexdigest()
    try:
        asset = _download(row, target)
        compressed_digest = hashlib.sha256()
        with asset.open("rb") as compressed:
            for chunk in iter(lambda: compressed.read(4 * 1024 * 1024), b""):
                compressed_digest.update(chunk)

        uncompressed_bytes = 0
        record_count = 0
        valid_record_count = 0
        invalid_record_count = 0
        identities: set[str] = set()
        with gzip.open(asset, "rb") as handle:
            for raw_line in handle:
                uncompressed_bytes += len(raw_line)
                record_count += 1
                try:
                    value = json.loads(raw_line.decode("utf-8"))
                    if not isinstance(value, Mapping):
                        raise ValueError("record is not an object")
                    identity = hashlib.sha256(
                        json.dumps(
                            value,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ).encode("utf-8")
                    ).hexdigest()
                    identities.add(identity)
                    valid_record_count += 1
                except (UnicodeDecodeError, ValueError, TypeError):
                    invalid_record_count += 1

        size_result = {
            "uncompressed_bytes": uncompressed_bytes,
            "compressed_bytes": int(row.get("bytes") or 0),
            "asset_sha256": compressed_digest.hexdigest(),
        }
        record_result = {
            "record_count": record_count,
            "valid_record_count": valid_record_count,
            "unique_record_count": len(identities),
            "invalid_record_count": invalid_record_count,
            "duplicate_record_count": valid_record_count - len(identities),
            "asset_sha256": compressed_digest.hexdigest(),
            "exact": True,
        }
        return dataset_id, size_result, record_result
    except Exception as exc:
        reason = f"{type(exc).__name__}:{str(exc)[:240]}"
        unavailable = {"status": "UNAVAILABLE", "reason": reason, "retryable": True}
        return dataset_id, dict(unavailable), dict(unavailable)
    finally:
        shutil.rmtree(target, ignore_errors=True)


def _resolved(table: Mapping[str, Any], dataset_id: str) -> bool:
    value = table.get(dataset_id)
    return dataset_id in table and not (
        isinstance(value, Mapping) and value.get("retryable") is True
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    worker_count = min(32, max(1, args.workers))

    index = json.loads(INDEX.read_text(encoding="utf-8"))
    rows = hydrate_default_release_repository(index)
    size_doc = (
        json.loads(SIZE_PATCH.read_text(encoding="utf-8"))
        if SIZE_PATCH.exists()
        else {"sizes": {}}
    )
    record_doc = (
        json.loads(RECORD_PATCH.read_text(encoding="utf-8"))
        if RECORD_PATCH.exists()
        else {"records": {}}
    )
    sizes = size_doc.get("sizes") if isinstance(size_doc.get("sizes"), dict) else {}
    records = (
        record_doc.get("records") if isinstance(record_doc.get("records"), dict) else {}
    )
    all_rows = [row for row in rows if isinstance(row, Mapping) and row.get("dataset_id")]

    for row in all_rows:
        dataset_id = str(row["dataset_id"])
        if not (row.get("release_repository") and row.get("release_tag") and row.get("release_asset")):
            unavailable = {
                "status": "UNAVAILABLE",
                "reason": "no_immutable_release_asset",
                "retryable": False,
            }
            sizes.setdefault(dataset_id, dict(unavailable))
            records.setdefault(dataset_id, dict(unavailable))

    candidates = sorted(
        [
            row
            for row in all_rows
            if not _resolved(sizes, str(row.get("dataset_id")))
            or not _resolved(records, str(row.get("dataset_id")))
        ],
        key=lambda row: str(row.get("dataset_id")),
    )[: max(1, args.limit)]

    failed: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="alina-measure-") as temporary_root:
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = [pool.submit(_measure_candidate, row, temporary_root) for row in candidates]
            for future in as_completed(futures):
                dataset_id, size_result, record_result = future.result()
                sizes[dataset_id] = size_result
                records[dataset_id] = record_result
                if size_result.get("status") == "UNAVAILABLE":
                    failed.append(
                        {"dataset_id": dataset_id, "reason": str(size_result.get("reason", ""))}
                    )

    remaining = sum(
        1
        for row in all_rows
        if not _resolved(sizes, str(row.get("dataset_id")))
        or not _resolved(records, str(row.get("dataset_id")))
    )
    exact_sizes = sum(
        1
        for value in sizes.values()
        if isinstance(value, Mapping) and isinstance(value.get("uncompressed_bytes"), int)
    )
    exact_records = sum(
        1
        for value in records.values()
        if isinstance(value, Mapping) and value.get("exact") is True
    )
    unavailable_sizes = sum(
        1
        for value in sizes.values()
        if isinstance(value, Mapping)
        and value.get("status") == "UNAVAILABLE"
        and value.get("retryable") is not True
    )
    unavailable_records = sum(
        1
        for value in records.values()
        if isinstance(value, Mapping)
        and value.get("status") == "UNAVAILABLE"
        and value.get("retryable") is not True
    )
    common = {
        "attempted": len(candidates),
        "failed": sorted(failed, key=lambda item: item["dataset_id"]),
        "remaining_assets": remaining,
        "coverage_complete": remaining == 0,
    }
    size_body = {
        "schema": "alina.uncompressed_size_patch.v2",
        "method": "parallel_exact_gzip_decompression_byte_count_or_explicit_unavailable",
        "sizes": dict(sorted(sizes.items())),
        "exact_assets": exact_sizes,
        "unavailable_assets": unavailable_sizes,
        **common,
    }
    record_body = {
        "schema": "alina.record_count_patch.v1",
        "method": "parallel_exact_jsonl_parse_and_canonical_within_shard_dedup",
        "records": dict(sorted(records.items())),
        "exact_assets": exact_records,
        "unavailable_assets": unavailable_records,
        **common,
    }
    SIZE_PATCH.write_text(json.dumps(size_body, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    RECORD_PATCH.write_text(
        json.dumps(record_body, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "attempted": len(candidates),
                "remaining_assets": remaining,
                "exact_size_assets": exact_sizes,
                "exact_record_assets": exact_records,
                "coverage_complete": remaining == 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
