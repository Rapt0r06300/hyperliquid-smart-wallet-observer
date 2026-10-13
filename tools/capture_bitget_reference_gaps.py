#!/usr/bin/env python3
"""Recover reference-only missing Bitget public trades as isolated evidence.

Read-only. Requires an already SHA-hydrated quarantined shard. The original
WebSocket trade stream and canonical catalogs NEVER change. REST-only trades
are preserved as source evidence, not merged, replay-ready, or SAFE.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.partitioned_data_index import read_index
    from tools.preservation_inventory import summarize
    from tools.reinspect_recovered_quarantine import reinspect
except ModuleNotFoundError:
    from partitioned_data_index import read_index
    from preservation_inventory import summarize
    from reinspect_recovered_quarantine import reinspect

REPO = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{64}\Z")
SYMBOL = re.compile(r"[A-Z0-9]{3,25}\Z")
MAX_PAGES = 6
MAX_MISSING = 64


def build_reference_gap_receipt(
    row: Mapping[str, Any], inspection: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
) -> dict[str, Any]:
    """Certify provenance/identity of a bounded REST comparison, NEVER its safety."""
    missing = reconciliation.get("missing_reference_evidence")
    if not isinstance(missing, Mapping):
        raise ValueError("BITGET_REFERENCE_GAP_NOT_AVAILABLE")
    if missing.get("status") != "REFERENCE_ONLY_NOT_MERGED_OR_REPLAY_CERTIFIED":
        raise ValueError("BITGET_REFERENCE_GAP_NOT_VERIFIABLE")
    if (reconciliation.get("status") not in {"PARTIAL", "MATCHED"}
            or type(reconciliation.get("live_count")) is not int
            or type(reconciliation.get("reference_count")) is not int
            or type(reconciliation.get("missing_from_live")) is not int
            or reconciliation.get("live_only") != 0
            or reconciliation.get("duplicate_live_keys") != 0):
        raise ValueError("BITGET_REFERENCE_RECONCILIATION_INCOMPLETE")
    rows = missing.get("rows")
    if (not isinstance(rows, list) or len(rows) != missing.get("missing_trade_count")
            or len(rows) != reconciliation["missing_from_live"]
            or len(rows) > MAX_MISSING
            or any(not isinstance(x, Mapping) for x in rows)):
        raise ValueError("BITGET_REFERENCE_MISSING_ROWS_COUNT_MISMATCH")
    if (missing.get("symbol") != str(row.get("symbol") or "").upper()
            or missing.get("comparison_start_ts_ms") != reconciliation.get("comparison_start_ts_ms")
            or missing.get("comparison_end_ts_ms") != reconciliation.get("comparison_end_ts_ms")
            or missing.get("original_live_trade_count") != reconciliation.get("live_count")):
        raise ValueError("BITGET_REFERENCE_WINDOW_OR_SYMBOL_CHANGED")
    import hashlib as _hashlib
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
    if (not isinstance(missing.get("rows_sha256"), str)
            or _hashlib.sha256(canonical).hexdigest() != missing["rows_sha256"]):
        raise ValueError("BITGET_REFERENCE_ROWS_DIGEST_MISMATCH")
    if (inspection.get("byte_coverage_verified") is not True
            or inspection.get("isolated_parse_chronology_compatible") is not True
            or inspection.get("reclassified_safe") is not False
            or inspection.get("replay_certified") is not False):
        raise ValueError("BITGET_REFERENCE_ORIGINAL_NOT_BYTE_VERIFIED")
    digest = inspection.get("catalog_index_sha256")
    original_sha = inspection.get("logical_shard_sha256")
    if (not isinstance(digest, str) or not SHA.fullmatch(digest)
            or not isinstance(original_sha, str) or not SHA.fullmatch(original_sha)
            or original_sha != str(row.get("sha256") or "").lower()
            or inspection.get("dataset_id") != row.get("dataset_id")):
        raise ValueError("BITGET_REFERENCE_ORIGINAL_IDENTITY_MISMATCH")
    original_state = row.get("quality_status")
    if original_state != "PARTIAL":
        raise ValueError("BITGET_REFERENCE_ONLY_PARTIAL_CANDIDATES")
    return {
        "schema": "alina.bitget_reference_gap_evidence.v1",
        "status": "REFERENCE_ROWS_PRESERVED_NOT_REPLAY_CERTIFIED",
        "source_repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "rest_endpoint": "https://api.bitget.com/api/v2/mix/market/fills-history",
        "source_category": "PUBLIC_REST_REFERENCE_NOT_LIVE_WEBSOCKET",
        "dataset_id": row["dataset_id"],
        "symbol": missing["symbol"],
        "catalog_index_sha256_at_probe": digest,
        "original_compressed_shard_sha256": original_sha,
        "original_quality_status": original_state,
        "original_live_trade_count": reconciliation["live_count"],
        "reference_trade_count_at_probe": reconciliation["reference_count"],
        "reference_missing_from_live_at_probe": reconciliation["missing_from_live"],
        "original_manifest_missing_from_live": (
            row.get("reconciliation", {}).get("missing_from_live")
            if isinstance(row.get("reconciliation"), Mapping) else None
        ),
        "original_missing_delta_matches_current_probe": (
            row.get("reconciliation", {}).get("missing_from_live") == reconciliation["missing_from_live"]
            if isinstance(row.get("reconciliation"), Mapping) else None
        ),
        "evidence_rows_sha256": missing["rows_sha256"],
        "reference_only_rows": rows,
        "byte_coverage_verified_original": True,
        "reference_response_is_historical": True,
        "all_missing_trade_records_recovered": False,
        "cross_shard_continuity_proven": False,
        "replay_certified": False, "validation_allowed": False,
        "proof_of_pnl_allowed": False, "reclassified_safe": False,
        "real_execution": False,
    }


def preserve_gap_receipt(root: Path, report: Mapping[str, Any]) -> Path:
    """Create one immutable receipt without overwriting prior evidence."""
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("BITGET_REFERENCE_UNSAFE_OUTPUT_DIRECTORY")
    name = report["dataset_id"]
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,220}", name):
        raise ValueError("BITGET_REFERENCE_UNSAFE_DATASET_ID")
    target = root / (name + ".bitget-rest-missing.json")
    if target.exists() or target.is_symlink():
        raise ValueError("BITGET_REFERENCE_REFUSE_OVERWRITE")
    raw = (json.dumps(dict(report), sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=root, prefix=".reference-gap-",
                                         suffix=".tmp", delete=False) as out:
            temporary = Path(out.name)
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.link(temporary, target)
        if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(raw).digest():
            raise ValueError("BITGET_REFERENCE_RECEIPT_WRITE_CONFLICT")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--destination", type=Path, required=True,
                        help="Existing byte-verified, unmodified quarantined recovery directory")
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--index", type=Path, default=REPO / "catalog/DATA_INDEX.json")
    parser.add_argument("--metrics", type=Path, default=REPO / "catalog/DATA_METRICS.json")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    parser.add_argument("--max-missing", type=int, default=MAX_MISSING)
    parser.add_argument("--execute", action="store_true",
                        help="Allow at most six public read-only Bitget REST requests")
    args = parser.parse_args(argv)
    try:
        if (type(args.max_pages) is not int or not 1 <= args.max_pages <= MAX_PAGES
                or type(args.max_missing) is not int or not 1 <= args.max_missing <= MAX_MISSING):
            raise ValueError("BITGET_REFERENCE_EXPLICIT_LIMIT_INVALID")
        raw = args.index.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        index = read_index(args.index)
        summary = summarize(index, json.loads(args.metrics.read_text(encoding="utf-8")), digest)
        if summary["status"] != "CATALOG_CLASSIFIED_NOT_RESTORED":
            raise ValueError("BITGET_REFERENCE_CATALOG_UNVERIFIED")
        matches = [row for row in index["shards"] if row.get("dataset_id") == args.dataset_id]
        if len(matches) != 1:
            raise ValueError("BITGET_REFERENCE_DATASET_NOT_UNIQUE")
        row = matches[0]
        if (row.get("venue") != "bitget" or row.get("family") != "trades"
                or row.get("quality_status") != "PARTIAL"
                or not isinstance(row.get("symbol"), str)
                or not SYMBOL.fullmatch(row["symbol"].upper())):
            raise ValueError("BITGET_REFERENCE_NOT_SUPPORTED_PARTIAL_TRADE")
        start, end = row.get("start_ts_ms"), row.get("end_ts_ms")
        if (type(start) is not int or type(end) is not int
                or start > end or end - start > 7 * 86400 * 1000):
            raise ValueError("BITGET_REFERENCE_INVALID_TIME_WINDOW")
        inspection = reinspect(index, digest, args.destination, args.dataset_id)
        if not args.execute:
            print(json.dumps({
                "status": "BITGET_REFERENCE_DRY_RUN_NOT_FETCHED",
                "dataset_id": args.dataset_id,
                "byte_coverage_verified": inspection["byte_coverage_verified"],
                "replay_certified": False, "reclassified_safe": False,
            }, sort_keys=True))
            return 0
        from hl_observer.collection.trade_reconciliation import reconcile_bitget_trade_shard
        from tools.restore_alina import _safe_component
        logical_sha = inspection["logical_shard_sha256"]
        path = (args.destination / "quarantine" / "source_verified_non_replay" /
                (_safe_component(args.dataset_id) + "." + logical_sha[:16] + ".jsonl.gz"))
        reconciliation = asyncio.run(reconcile_bitget_trade_shard(
            path, symbol=row["symbol"].upper(), start_ms=start, end_ms=end,
            max_pages=args.max_pages, missing_reference_rows_limit=args.max_missing,
        ))
        receipt = build_reference_gap_receipt(row, inspection, reconciliation)
        if args.output_directory.resolve() != args.destination.resolve() and not args.output_directory.resolve().is_relative_to(args.destination.resolve()):
            raise ValueError("BITGET_REFERENCE_OUTPUT_MUST_BE_QUARANTINED")
        result_path = preserve_gap_receipt(args.output_directory, receipt)
        print(json.dumps({k: v for k, v in receipt.items() if k != "reference_only_rows"}
                         | {"output": str(result_path)}, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, UnicodeError, KeyError) as exc:
        print(json.dumps({"status": "BITGET_REFERENCE_INCOMPLETE_NOT_SAFE",
                          "reason": str(exc)[:500]}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
