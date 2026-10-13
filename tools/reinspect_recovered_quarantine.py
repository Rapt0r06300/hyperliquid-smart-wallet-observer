#!/usr/bin/env python3
"""Reinspect byte-verified historical quarantine with Alina's existing replay policy.

Offline, read-only, fail-closed. This validates one hydrated shard's stream,
chronology and (when applicable) trade identities. It NEVER promotes SAFE,
authorizes a backtest or proves cross-shard market completeness.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.partitioned_data_index import read_index
    from tools.preservation_inventory import summarize
    from tools.recover_one_quarantined_shard import candidate_from_index
    from tools.replay_compatibility import inspect_asset, VERIFIER_VERSION
    from tools.restore_alina import _safe_component, _sha256
    from tools.verify_quarantine_recovery import verify_quarantine
except ModuleNotFoundError:
    from partitioned_data_index import read_index
    from preservation_inventory import summarize
    from recover_one_quarantined_shard import candidate_from_index
    from replay_compatibility import inspect_asset, VERIFIER_VERSION
    from restore_alina import _safe_component, _sha256
    from verify_quarantine_recovery import verify_quarantine

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_COMPRESSED = 100_000_000
MAX_UNCOMPRESSED = 256_000_000


def _bounded_uncompressed_size(path: Path, *, max_bytes: int) -> int:
    if type(max_bytes) is not int or max_bytes < 1 or max_bytes > 1_000_000_000:
        raise ValueError("REINSPECTION_INVALID_DECOMPRESSION_BUDGET")
    total = 0
    try:
        with gzip.open(path, "rb") as stream:
            while True:
                chunk = stream.read(min(1024 * 1024, max_bytes - total + 1))
                if not chunk:
                    return total
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("REINSPECTION_UNCOMPRESSED_SIZE_BUDGET_EXCEEDED")
    except (EOFError, OSError, gzip.BadGzipFile) as exc:
        raise ValueError("REINSPECTION_INVALID_GZIP_STREAM") from exc



def _embedded_gap_signals(path: Path, *, max_bytes: int) -> dict[str, Any]:
    """Report only explicit per-record markers, not proof of continuous capture."""
    records_with_markers = 0
    explicit_gap_events = 0
    snapshot_markers = 0
    rows_without_markers = 0
    unparsable_rows = 0
    scanned = 0
    with gzip.open(path, "rt", encoding="utf-8") as source:
        for line in source:
            scanned += len(line.encode("utf-8"))
            if scanned > max_bytes:
                raise ValueError("REINSPECTION_EMBEDDED_GAP_SCAN_EXCEEDED")
            try:
                event = json.loads(line)
            except (ValueError, TypeError):
                unparsable_rows += 1
                continue
            if not isinstance(event, Mapping):
                unparsable_rows += 1
                continue
            gap = event.get("gap_count")
            if type(gap) is int and gap >= 0:
                records_with_markers += 1
                explicit_gap_events += gap
            else:
                rows_without_markers += 1
            summary = event.get("parsed_summary")
            if isinstance(summary, Mapping) and summary.get("action") == "snapshot":
                snapshot_markers += 1
    return {
        "explicit_event_gap_marker_rows": records_with_markers,
        "explicit_event_gap_total": explicit_gap_events,
        "rows_without_explicit_gap_marker": rows_without_markers,
        "unparsed_row_count": unparsable_rows,
        "reported_snapshot_rows": snapshot_markers,
        "absence_of_source_gaps_proven": False,
    }


def reinspect(index: Mapping[str, Any], index_sha: str,
              root: Path, dataset_id: str, *, repo_root: Path = ROOT,
              max_uncompressed_bytes: int = MAX_UNCOMPRESSED) -> dict[str, Any]:
    if not isinstance(index_sha, str) or not SHA.fullmatch(index_sha):
        raise ValueError("REINSPECTION_INVALID_CATALOG_SHA")
    root = Path(root)
    repo_root = Path(repo_root)
    if (root.is_symlink() or not root.is_dir()
            or repo_root.is_symlink() or not repo_root.is_dir()):
        raise ValueError("REINSPECTION_UNSAFE_ROOT")
    candidate = candidate_from_index(index, dataset_id)
    row = next(item for item in index["shards"] if item["dataset_id"] == dataset_id)
    relative = row.get("manifest_path")
    if (not isinstance(relative, str) or not relative.startswith("datasets/")
            or "\\\\" in relative or any(part in ("", ".", "..") for part in relative.split("/"))):
        raise ValueError("REINSPECTION_INVALID_MANIFEST_PATH")
    manifest_path = repo_root / relative
    if (manifest_path.is_symlink()
            or not manifest_path.resolve().is_relative_to(repo_root.resolve())):
        raise ValueError("REINSPECTION_UNSAFE_MANIFEST")
    if manifest_path.is_file():
        if manifest_path.stat().st_size > 2_000_000:
            raise ValueError("REINSPECTION_MANIFEST_TOO_LARGE")
        raw_manifest = manifest_path.read_bytes()
    else:
        # Hosted recovery uses sparse checkout of catalog + tools. The exact
        # original manifest blob is still reachable from HEAD without
        # expanding 400k+ manifest files into the checkout.
        source = "HEAD:" + relative
        size_result = subprocess.run(
            ["git", "-C", str(repo_root), "cat-file", "-s", source],
            capture_output=True, text=True, timeout=20, check=False,
        )
        if size_result.returncode != 0:
            raise ValueError("REINSPECTION_MANIFEST_GIT_BLOB_MISSING")
        try:
            git_bytes = int(size_result.stdout.strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("REINSPECTION_MANIFEST_GIT_SIZE_INVALID") from exc
        if not 0 < git_bytes <= 2_000_000:
            raise ValueError("REINSPECTION_MANIFEST_GIT_SIZE_BUDGET")
        result = subprocess.run(
            ["git", "-C", str(repo_root), "show", source],
            capture_output=True, timeout=20, check=False,
        )
        if result.returncode != 0 or len(result.stdout) != git_bytes:
            raise ValueError("REINSPECTION_MANIFEST_GIT_BLOB_INCOMPLETE")
        raw_manifest = result.stdout
    manifest = json.loads(raw_manifest)
    if (not isinstance(manifest, dict)
            or manifest.get("dataset_id") != dataset_id
            or manifest.get("quality_status") != candidate["quality_status"]
            or str(manifest.get("sha256") or "").lower() != candidate["logical_sha256"]
            or manifest.get("bytes") != candidate["logical_bytes"]):
        raise ValueError("REINSPECTION_MANIFEST_CATALOG_IDENTITY_MISMATCH")
    # Existing authoritative byte-coverage verifier rechecks original Release
    # outer ZIP digest AND extracted compressed inner shard digest.
    coverage = verify_quarantine(root, index, index_sha)
    if (coverage["receipts_found"] != 1
            or coverage["byte_verified_non_safe_shards"] != 1
            or coverage["invalid_or_stale_receipts"] != 0):
        raise ValueError("REINSPECTION_QUARANTINE_BYTES_NOT_VERIFIED")
    logical_sha = candidate["logical_sha256"]
    name = _safe_component(dataset_id) + "." + logical_sha[:16] + ".jsonl.gz"
    directory = root / "quarantine" / "source_verified_non_replay"
    path = directory / name
    if (directory.is_symlink() or path.is_symlink() or not path.is_file()
            or path.stat().st_size != candidate["logical_bytes"]
            or path.stat().st_size > MAX_COMPRESSED
            or _sha256(path) != logical_sha):
        raise ValueError("REINSPECTION_LOGICAL_SHARD_NOT_VERIFIED")
    uncompressed_size = _bounded_uncompressed_size(path, max_bytes=max_uncompressed_bytes)
    event_gap_signals = _embedded_gap_signals(path, max_bytes=max_uncompressed_bytes)
    manifest_integrity = manifest.get("integrity")
    reported_gap = manifest_integrity.get("gap_count") if isinstance(manifest_integrity, Mapping) else None
    reported_drops = manifest.get("collection_queue_drops")
    if (reported_gap is not None and (type(reported_gap) is not int or reported_gap < 0)):
        raise ValueError("REINSPECTION_INVALID_MANIFEST_GAP_COUNTER")
    if (reported_drops is not None and (type(reported_drops) is not int or reported_drops < 0)):
        raise ValueError("REINSPECTION_INVALID_QUEUE_DROP_COUNTER")
    parsed = inspect_asset(path, manifest)
    if (not isinstance(parsed, dict)
            or parsed.get("verifier_version") != VERIFIER_VERSION
            or type(parsed.get("record_count")) is not int
            or type(parsed.get("invalid_record_count")) is not int):
        raise ValueError("REINSPECTION_INVALID_PARSER_RECEIPT")
    isolated_replay_ok = parsed.get("replay_compatible") is True
    return {
        "schema": "alina.quarantined_replay_reinspection.v1",
        "status": (
            "CONTENT_REPLAY_CHECK_PASSED_NOT_SAFE" if isolated_replay_ok
            else "CONTENT_REPLAY_CHECK_FAILED_NOT_SAFE"
        ),
        "dataset_id": dataset_id,
        "family": row.get("family"),
        "quality_status_unchanged": row["quality_status"],
        "catalog_index_sha256": index_sha,
        "immutable_manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
        "logical_shard_sha256": logical_sha,
        "logical_shard_compressed_bytes": candidate["logical_bytes"],
        "logical_shard_uncompressed_bytes_scanned": uncompressed_size,
        "outer_release_sha256": candidate["outer_sha256"],
        "outer_release_bytes": candidate["outer_bytes"],
        "byte_coverage_verified": True,
        "replay_verifier_version": VERIFIER_VERSION,
        "isolated_parse_chronology_compatible": isolated_replay_ok,
        "inspection": parsed,
        "observed_event_gap_signals": event_gap_signals,
        "manifest_integrity_gap_count": reported_gap,
        "manifest_collection_queue_drops": reported_drops,
        "manifest_gap_exceeds_explicit_event_markers": (
            reported_gap > event_gap_signals["explicit_event_gap_total"]
            if type(reported_gap) is int and event_gap_signals["explicit_event_gap_marker_rows"] else None
        ),
        "gap_provenance_reconciled": False,
        "replay_certified": False,
        "reclassified_safe": False,
        "validation_allowed": False,
        "proof_of_pnl_allowed": False,
        "cross_shard_continuity_proven": False,
        "all_exploitable_data_restored": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--index", type=Path, default=ROOT / "catalog/DATA_INDEX.json")
    parser.add_argument("--metrics", type=Path, default=ROOT / "catalog/DATA_METRICS.json")
    parser.add_argument("--max-uncompressed-bytes", type=int, default=MAX_UNCOMPRESSED)
    args = parser.parse_args(argv)
    try:
        raw = args.index.read_bytes()
        index = read_index(args.index)
        metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
        digest = hashlib.sha256(raw).hexdigest()
        summarize(index, metrics, digest)
        receipt = reinspect(index, digest, args.destination, args.dataset_id,
                            max_uncompressed_bytes=args.max_uncompressed_bytes)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        print(json.dumps({"status": "REINSPECTION_INCOMPLETE", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
