#!/usr/bin/env python3
"""Bounded official-reference recheck of ONE byte-verified Bitget trade shard.

This reuses Alina's existing ID-based reconciler. It never fabricates missing
trades, writes canonical shards, changes SAFE labels, or approves backtests.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

try:
    from tools.partitioned_data_index import read_index
    from tools.preservation_inventory import summarize
    from tools.reinspect_recovered_quarantine import reinspect
    from tools.recover_one_quarantined_shard import candidate_from_index
    from tools.restore_alina import _safe_component
except ModuleNotFoundError:
    from partitioned_data_index import read_index
    from preservation_inventory import summarize
    from reinspect_recovered_quarantine import reinspect
    from recover_one_quarantined_shard import candidate_from_index
    from restore_alina import _safe_component

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{64}\Z")
SYMBOL = re.compile(r"[A-Z0-9]{2,32}\Z")


async def recheck_one(index: Mapping[str, Any], index_digest: str,
                      destination: Path, dataset_id: str, *,
                      repo_root: Path = ROOT, max_pages: int = 8,
                      reference_gap_export_limit: int = 0,
                      reconciliation_function: Callable[..., Awaitable[dict[str, Any]]] | None = None
                      ) -> dict[str, Any]:
    if not SHA.fullmatch(index_digest):
        raise ValueError("REFERENCE_RECHECK_INVALID_CATALOG_ID")
    if type(max_pages) is not int or not 1 <= max_pages <= 12:
        raise ValueError("REFERENCE_RECHECK_INVALID_PAGE_LIMIT")
    if (type(reference_gap_export_limit) is not int
            or not 0 <= reference_gap_export_limit <= 128):
        raise ValueError("REFERENCE_RECHECK_INVALID_REFERENCE_EXPORT_LIMIT")
    candidate = candidate_from_index(index, dataset_id)
    row = next(x for x in index["shards"] if x["dataset_id"] == dataset_id)
    # Reverify both the immutable outer Release and compressed inner shard
    # before any official REST comparison.
    inspection = reinspect(index, index_digest, destination, dataset_id,
                           repo_root=repo_root)
    if inspection.get("byte_coverage_verified") is not True:
        raise ValueError("REFERENCE_RECHECK_SOURCE_BYTES_UNVERIFIED")
    common = {
        "schema": "alina.quarantine_official_trade_recheck.v1",
        "catalog_index_sha256": index_digest,
        "dataset_id": dataset_id,
        "original_quality_status": row.get("quality_status"),
        "immutable_shard_sha256": candidate["logical_sha256"],
        "original_replay_content_status": inspection.get("status"),
        "reference_recheck_repair_count": 0,
        "reclassified_safe": False, "replay_certified": False,
        "validation_allowed": False, "proof_of_pnl_allowed": False,
        "paper_only": True, "read_only": True,
    }
    if row.get("family") != "trades" or str(row.get("venue") or "").lower() != "bitget":
        return {**common, "status": "REFERENCE_NOT_APPLICABLE"}
    symbol = str(row.get("symbol") or "").upper()
    if not SYMBOL.fullmatch(symbol):
        raise ValueError("REFERENCE_RECHECK_INVALID_SYMBOL")
    root = Path(destination)
    file = (root / "quarantine" / "source_verified_non_replay" /
            (_safe_component(dataset_id) + "." + candidate["logical_sha256"][:16] + ".jsonl.gz"))
    if reconciliation_function is None:
        from hl_observer.collection.trade_reconciliation import reconcile_bitget_trade_shard
        reconciliation_function = reconcile_bitget_trade_shard
    kwargs = {
        "symbol": symbol,
        "start_ms": int(row.get("start_ts_ms") or 0),
        "end_ms": int(row.get("end_ts_ms") or 0),
        "limit": 1000, "max_pages": max_pages,
    }
    if reference_gap_export_limit:
        kwargs["missing_reference_rows_limit"] = reference_gap_export_limit
    report = await reconciliation_function(file, **kwargs)
    if not isinstance(report, dict):
        raise ValueError("REFERENCE_RECHECK_INVALID_SOURCE_REPORT")
    state = str(report.get("status") or "").upper()
    if state not in ("MATCHED", "PARTIAL", "UNAVAILABLE", "MISMATCH", "ERROR"):
        raise ValueError("REFERENCE_RECHECK_UNRECOGNIZED_SOURCE_STATUS")
    if reference_gap_export_limit:
        evidence = report.get("missing_reference_evidence")
        if not isinstance(evidence, dict):
            raise ValueError("REFERENCE_RECHECK_MISSING_EXPLICIT_GAP_RECEIPT")
        gap_status = evidence.get("status")
        if gap_status == "REFERENCE_ONLY_NOT_MERGED_OR_REPLAY_CERTIFIED":
            rows = evidence.get("rows")
            gap_count = evidence.get("missing_trade_count")
            if (not isinstance(rows, list) or type(gap_count) is not int
                    or gap_count < 0 or gap_count > reference_gap_export_limit
                    or len(rows) != gap_count
                    or gap_count != report.get("missing_from_live")
                    or evidence.get("symbol") != symbol
                    or evidence.get("validation_allowed") is not False
                    or evidence.get("replay_certified") is not False
                    or evidence.get("reclassified_safe") is not False):
                raise ValueError("REFERENCE_RECHECK_GAP_RECEIPT_INCONSISTENT")
            payload = json.dumps(
                rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            if hashlib.sha256(payload).hexdigest() != evidence.get("rows_sha256"):
                raise ValueError("REFERENCE_RECHECK_GAP_DIGEST_MISMATCH")
        elif gap_status in (
            "REFERENCE_GAP_EXCEEDS_BOUND_NOT_EXPORTED",
            "REFERENCE_GAP_INVALID_SOURCE_FIELDS_NOT_EXPORTED",
        ):
            if "rows" in evidence:
                raise ValueError("REFERENCE_RECHECK_UNSAFE_GAP_ROWS")
        else:
            raise ValueError("REFERENCE_RECHECK_UNKNOWN_GAP_STATUS")
    if state == "MATCHED":
        conclusion = "OFFICIAL_REFERENCE_MATCHED_NOT_SAFE"
    elif state in ("PARTIAL", "MISMATCH"):
        conclusion = "OFFICIAL_REFERENCE_INCOMPLETE_NOT_SAFE"
    else:
        conclusion = "OFFICIAL_REFERENCE_UNAVAILABLE_NOT_SAFE"
    return {
        **common, "status": conclusion,
        "venue": "bitget", "symbol": symbol,
        "max_reference_pages": max_pages,
        "reference_gap_export_limit": reference_gap_export_limit,
        "rest_only_missing_trades_not_merged": True,
        "original_manifest_missing_reference_trades": inspection.get(
            "manifest_reference_trades_missing_from_live"),
        "official_reference": report,
        "historical_reference_currently_rechecked": state in ("MATCHED", "PARTIAL", "MISMATCH"),
        "source_live_bytes_unchanged": True,
        "cross_shard_continuity_proven": False,
        "missing_trade_events_reconstructed": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--index", type=Path, default=ROOT / "catalog/DATA_INDEX.json")
    parser.add_argument("--metrics", type=Path, default=ROOT / "catalog/DATA_METRICS.json")
    parser.add_argument("--max-pages", type=int, default=8)
    parser.add_argument("--reference-gap-export-limit", type=int, default=0,
                        help="Opt-in max 128 official REST-only missing trade rows, never merge to WS")
    args = parser.parse_args(argv)
    try:
        raw = args.index.read_bytes()
        index = read_index(args.index)
        metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
        sha = hashlib.sha256(raw).hexdigest()
        summarize(index, metrics, sha)
        receipt = asyncio.run(recheck_one(
            index, sha, args.destination, args.dataset_id,
            max_pages=args.max_pages,
            reference_gap_export_limit=args.reference_gap_export_limit))
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        print(json.dumps({"status": "OFFICIAL_RECHECK_INCOMPLETE",
                          "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
