#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "catalog" / "DATA_INDEX.json"
METRICS = ROOT / "catalog" / "DATA_METRICS.json"
UNIQUE_PATCH = ROOT / "catalog" / "TRADE_UNIQUE_COUNT_PATCH.json"
TRADE_COUNT_PATCH = ROOT / "catalog" / "TRADE_COUNT_PATCH.json"
UNCOMPRESSED_PATCH = ROOT / "catalog" / "UNCOMPRESSED_SIZE_PATCH.json"
RECORD_PATCH = ROOT / "catalog" / "RECORD_COUNT_PATCH.json"
TRADE_FAMILIES = {
    "trades",
    "agg_trades",
    "fills",
    "userfills",
    "user_fills",
    "copy_vault_fills",
}
BYBIT_IDENTITY_VERSION = "full_native_or_deterministic_composite_string_v3"
GLOBAL_IDENTITY_VERSION = "native-id-or-venue-family-symbol-time-side-price-size-v3-full-string"


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _bucket(table: dict[str, dict[str, int]], key: str) -> dict[str, int]:
    if key not in table:
        table[key] = {
            "shards": 0,
            "records": 0,
            "trades": 0,
            "unique_trades_within_shards": 0,
            "safe_trades": 0,
            "replayable_trades": 0,
            "bytes": 0,
            "uncompressed_bytes": 0,
            "uncompressed_exact_assets": 0,
            "uncompressed_unavailable_assets": 0,
            "trade_shards_exact": 0,
            "trade_shards_missing_exact": 0,
        }
    return table[key]


def build() -> dict[str, Any]:
    idx = json.loads(INDEX.read_text(encoding="utf-8"))
    shards = idx.get("shards") or []
    size_doc = {}
    try:
        size_doc = json.loads(UNCOMPRESSED_PATCH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        size_doc = {}
    size_rows = size_doc.get("sizes") if isinstance(size_doc, dict) else {}
    if not isinstance(size_rows, dict):
        size_rows = {}
    record_doc = {}
    try:
        record_doc = json.loads(RECORD_PATCH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        record_doc = {}
    record_rows = record_doc.get("records") if isinstance(record_doc, dict) else {}
    if not isinstance(record_rows, dict):
        record_rows = {}

    trade_doc = {}
    try:
        trade_doc = json.loads(TRADE_COUNT_PATCH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        trade_doc = {}
    trade_rows = trade_doc.get("counts") if isinstance(trade_doc, dict) else {}
    if not isinstance(trade_rows, dict):
        trade_rows = {}
    totals: dict[str, Any] = {
        "TOTAL_SHARDS": len(shards),
        "TOTAL_RELEASES": 0,
        "MIN_COLLECTION_TS_MS": None,
        "MAX_COLLECTION_TS_MS": None,
        "TOTAL_L2_RECORDS": 0,
        "TOTAL_BBO_RECORDS": 0,
        "SAFE_SHARDS": 0,
        "PARTIAL_SHARDS": 0,
        "REJECTED_SHARDS": 0,
        "REPLAYABLE_SHARDS": 0,
        "TOTAL_TRADES_COLLECTED": 0,
        "TOTAL_TRADES_SAFE": 0,
        "TOTAL_TRADES_PARTIAL": 0,
        "TOTAL_TRADES_REJECTED": 0,
        "TOTAL_TRADES_REPLAYABLE": 0,
        "TOTAL_UNIQUE_TRADES_WITHIN_SHARDS": 0,
        "TOTAL_RECORDS": 0,
        "TOTAL_VALID_RECORDS": 0,
        "TOTAL_UNIQUE_RECORDS": 0,
        "TOTAL_SAFE_RECORDS": 0,
        "TOTAL_REPLAYABLE_RECORDS": 0,
        "TOTAL_INVALID_RECORDS": 0,
        "TOTAL_DUPLICATE_RECORDS": 0,
        "TOTAL_GAP_RECORDS": 0,
        "TOTAL_QUARANTINED_RECORDS": 0,
        "TOTAL_REJECTED_RECORDS": 0,
        "TOTAL_COMPRESSED_BYTES": 0,
        "TOTAL_UNCOMPRESSED_BYTES": 0,
        "UNCOMPRESSED_SIZE_EXACT_ASSETS": 0,
        "UNCOMPRESSED_SIZE_UNAVAILABLE_ASSETS": 0,
        "UNCOMPRESSED_SIZE_UNCLASSIFIED_ASSETS": 0,
        "TRADE_SHARDS_WITH_EXACT_COUNT": 0,
        "TRADE_SHARDS_MISSING_EXACT_COUNT": 0,
        "TRADE_COUNT_FAILURE_REASON_COUNT": 0,
        "TRADE_SHARDS_WITH_EXACT_UNIQUE_COUNT": 0,
        "TRADE_SHARDS_MISSING_EXACT_UNIQUE_COUNT": 0,
        "GLOBAL_UNIQUE_FAILURE_REASON_COUNT": 0,
        "TOTAL_CROSS_SHARD_OVERLAP_TRADES": 0,
    }
    by_venue: dict[str, dict[str, int]] = {}
    by_symbol: dict[str, dict[str, int]] = {}
    by_family: dict[str, dict[str, int]] = {}
    valid_record_count_missing = 0
    unique_record_count_missing = 0
    unique_unavailable_ids: set[str] = set()
    release_tags: set[str] = set()
    start_times: list[int] = []
    end_times: list[int] = []
    manifest_trade_identities: set[str] = set()
    manifest_identity_complete = True
    manifest_trade_shards = 0
    try:
        unique_doc_early = json.loads(UNIQUE_PATCH.read_text(encoding="utf-8"))
        unavailable_early = unique_doc_early.get("unavailable") if isinstance(unique_doc_early, dict) else {}
        if isinstance(unavailable_early, dict):
            unique_unavailable_ids = set(unavailable_early)
    except (OSError, ValueError, TypeError):
        pass
    totals["TRADE_SHARDS_UNIQUE_COUNT_UNAVAILABLE"] = 0

    for row in shards:
        if not isinstance(row, dict):
            continue
        status = str(row.get("quality_status") or "")
        replay = row.get("replay_compatible") is True
        dataset_id = str(row.get("dataset_id") or "")
        trade_entry = trade_rows.get(dataset_id)
        trade_entry_valid = (
            isinstance(trade_entry, dict)
            and len(str(row.get("sha256") or "")) == 64
            and str(trade_entry.get("asset_sha256") or "").lower()
                == str(row.get("sha256") or "").lower()
        )
        record_entry = record_rows.get(dataset_id)
        if isinstance(record_entry, dict) and record_entry.get("exact") is True:
            records = _int(record_entry.get("record_count"))
            valid_records = _int(record_entry.get("valid_record_count"))
            unique_records = _int(record_entry.get("unique_record_count"))
            invalid = _int(record_entry.get("invalid_record_count"))
            duplicates = _int(record_entry.get("duplicate_record_count"))
        else:
            records = _int(row.get("record_count") or row.get("event_count"))
            invalid = _int(row.get("invalid_record_count"))
            duplicates = _int(row.get("duplicate_count"))
            if isinstance(record_entry, dict) and record_entry.get("status") == "UNAVAILABLE" and record_entry.get("retryable") is not True:
                valid_records = 0
                unique_records = 0
            else:
                valid_record_count_missing += 1
                unique_record_count_missing += 1
                valid_records = 0
                unique_records = 0
        gaps = _int(row.get("gap_count"))
        compressed = _int(row.get("bytes"))
        release_tag = str(row.get("release_tag") or "").strip()
        if release_tag:
            release_tags.add(release_tag)
        if isinstance(row.get("start_ts_ms"), int):
            start_times.append(int(row["start_ts_ms"]))
        if isinstance(row.get("end_ts_ms"), int):
            end_times.append(int(row["end_ts_ms"]))
        size_entry = size_rows.get(str(row.get("dataset_id")))
        if isinstance(size_entry, dict) and isinstance(size_entry.get("uncompressed_bytes"), int):
            uncompressed = int(size_entry["uncompressed_bytes"])
            totals["UNCOMPRESSED_SIZE_EXACT_ASSETS"] += 1
        elif (
            row.get("uncompressed_size_exact") is True
            and isinstance(row.get("uncompressed_bytes"), int)
            and not isinstance(row.get("uncompressed_bytes"), bool)
            and int(row["uncompressed_bytes"]) >= 0
        ):
            uncompressed = int(row["uncompressed_bytes"])
            totals["UNCOMPRESSED_SIZE_EXACT_ASSETS"] += 1
        elif isinstance(size_entry, dict) and size_entry.get("status") == "UNAVAILABLE":
            uncompressed = 0
            totals["UNCOMPRESSED_SIZE_UNAVAILABLE_ASSETS"] += 1
        else:
            uncompressed = 0
            totals["UNCOMPRESSED_SIZE_UNCLASSIFIED_ASSETS"] += 1
        family = str(row.get("family") or "").lower()
        trade_family = family in TRADE_FAMILIES

        if trade_family and trade_entry_valid and trade_entry.get("trade_count_exact") is True:
            trade_exact = True
            trades = _int(trade_entry.get("trade_count"))
        else:
            trade_exact = trade_family and row.get("trade_count_exact") is True
            trades = _int(row.get("trade_count")) if trade_exact else 0

        bybit_stale_identity = (
            trade_family
            and str(row.get("venue") or "").lower() == "bybit"
            and trade_entry_valid
            and str(trade_entry.get("unique_identity_method") or "") != BYBIT_IDENTITY_VERSION
        )
        if (
            trade_family
            and trade_entry_valid
            and trade_entry.get("unique_trade_count_exact") is True
            and not bybit_stale_identity
        ):
            unique_exact = True
            unique_trades = _int(trade_entry.get("unique_trade_count"))
        elif bybit_stale_identity:
            unique_exact = False
            unique_trades = 0
        else:
            unique_exact = trade_family and row.get("unique_trade_count_exact") is True
            unique_trades = _int(row.get("unique_trade_count")) if unique_exact else 0
        if family in {"l2book", "copy_vault_l2", "native_market"}:
            totals["TOTAL_L2_RECORDS"] += records
        if family == "bbo":
            totals["TOTAL_BBO_RECORDS"] += records

        totals["TOTAL_RECORDS"] += records
        totals["TOTAL_VALID_RECORDS"] += valid_records
        totals["TOTAL_UNIQUE_RECORDS"] += unique_records
        totals["TOTAL_INVALID_RECORDS"] += invalid
        totals["TOTAL_DUPLICATE_RECORDS"] += duplicates
        totals["TOTAL_GAP_RECORDS"] += gaps
        if status in {"PARTIAL", "QUARANTINE", "QUARANTINED"}:
            totals["TOTAL_QUARANTINED_RECORDS"] += records
        if status in {"REJECT", "REJECTED"}:
            totals["TOTAL_REJECTED_RECORDS"] += records
        totals["TOTAL_COMPRESSED_BYTES"] += compressed
        totals["TOTAL_UNCOMPRESSED_BYTES"] += uncompressed

        if status == "SAFE":
            totals["SAFE_SHARDS"] += 1
            totals["TOTAL_SAFE_RECORDS"] += records
            totals["TOTAL_TRADES_SAFE"] += trades
        elif status == "PARTIAL":
            totals["PARTIAL_SHARDS"] += 1
            totals["TOTAL_TRADES_PARTIAL"] += trades
        elif status in {"REJECT", "REJECTED"}:
            totals["REJECTED_SHARDS"] += 1
            totals["TOTAL_TRADES_REJECTED"] += trades

        if replay:
            totals["REPLAYABLE_SHARDS"] += 1
            totals["TOTAL_REPLAYABLE_RECORDS"] += records
            totals["TOTAL_TRADES_REPLAYABLE"] += trades

        if trade_family:
            manifest_trade_shards += 1
            identity_rows = row.get("trade_identity_digests")
            identity_exact = row.get("trade_identity_digests_exact") is True
            valid_identity_rows = (
                isinstance(identity_rows, list)
                and all(
                    isinstance(value, str)
                    and re.fullmatch(r"[0-9a-f]{64}", value) is not None
                    for value in identity_rows
                )
                and len(set(identity_rows)) == unique_trades
            )
            if unique_exact and identity_exact and valid_identity_rows:
                manifest_trade_identities.update(identity_rows)
            else:
                manifest_identity_complete = False
            if trade_exact:
                totals["TRADE_SHARDS_WITH_EXACT_COUNT"] += 1
                totals["TOTAL_TRADES_COLLECTED"] += trades
            else:
                totals["TRADE_SHARDS_MISSING_EXACT_COUNT"] += 1
            if unique_exact:
                totals["TRADE_SHARDS_WITH_EXACT_UNIQUE_COUNT"] += 1
                totals["TOTAL_UNIQUE_TRADES_WITHIN_SHARDS"] += unique_trades
            elif dataset_id in unique_unavailable_ids:
                totals["TRADE_SHARDS_UNIQUE_COUNT_UNAVAILABLE"] += 1
            else:
                totals["TRADE_SHARDS_MISSING_EXACT_UNIQUE_COUNT"] += 1

        for table, key in (
            (by_venue, str(row.get("venue") or "unknown").lower()),
            (by_symbol, str(row.get("symbol") or "unknown").upper()),
            (by_family, family or "unknown"),
        ):
            bucket = _bucket(table, key)
            bucket["shards"] += 1
            bucket["records"] += records
            bucket["bytes"] += compressed
            bucket["uncompressed_bytes"] += uncompressed
            if isinstance(size_entry, dict) and isinstance(size_entry.get("uncompressed_bytes"), int):
                bucket["uncompressed_exact_assets"] += 1
            elif isinstance(size_entry, dict) and size_entry.get("status") == "UNAVAILABLE":
                bucket["uncompressed_unavailable_assets"] += 1
            if trade_family:
                if trade_exact:
                    bucket["trades"] += trades
                    bucket["trade_shards_exact"] += 1
                else:
                    bucket["trade_shards_missing_exact"] += 1
                if unique_exact:
                    bucket["unique_trades_within_shards"] += unique_trades
                if status == "SAFE":
                    bucket["safe_trades"] += trades
                if replay:
                    bucket["replayable_trades"] += trades

    totals["TOTAL_RELEASES"] = len(release_tags)
    totals["MIN_COLLECTION_TS_MS"] = min(start_times) if start_times else None
    totals["MAX_COLLECTION_TS_MS"] = max(end_times) if end_times else None

    totals["TRADE_COUNT_FAILURE_REASON_COUNT"] = (
        len(trade_doc.get("failure_reasons") or {})
        if isinstance(trade_doc, dict)
        else 0
    )
    totals["TOTAL_TRADES_COUNT_COVERAGE_COMPLETE"] = (
        totals["TRADE_SHARDS_MISSING_EXACT_COUNT"] == 0
    )
    unique_patch = {}
    global_unique = None
    global_unique_digest = None
    global_unique_complete = False
    if UNIQUE_PATCH.is_file():
        try:
            unique_patch = json.loads(UNIQUE_PATCH.read_text(encoding="utf-8"))
            if isinstance(unique_patch, dict):
                unique_identity_current = (
                    str(unique_patch.get("identity_version") or "") == GLOBAL_IDENTITY_VERSION
                )
                global_unique = (
                    unique_patch.get("global_unique_trade_count")
                    if unique_identity_current
                    else None
                )
                global_unique_digest = (
                    unique_patch.get("global_identity_digest")
                    if unique_identity_current
                    else None
                )
                global_unique_complete = (
                    unique_patch.get("coverage_complete") is True
                    and unique_identity_current
                )
                totals["GLOBAL_UNIQUE_FAILURE_REASON_COUNT"] = len(unique_patch.get("failure_reasons") or {})
                totals["TOTAL_CROSS_SHARD_OVERLAP_TRADES"] = _int(unique_patch.get("cross_shard_overlap_count"))
        except (OSError, ValueError, TypeError):
            global_unique = None
    if (
        not global_unique_complete
        and manifest_trade_shards > 0
        and manifest_identity_complete
    ):
        global_unique = len(manifest_trade_identities)
        global_unique_digest = hashlib.sha256(
            ("\n".join(sorted(manifest_trade_identities)) + "\n").encode("ascii")
        ).hexdigest()
        global_unique_complete = True
        totals["TOTAL_CROSS_SHARD_OVERLAP_TRADES"] = (
            totals["TOTAL_UNIQUE_TRADES_WITHIN_SHARDS"] - global_unique
        )
        totals["GLOBAL_UNIQUE_FAILURE_REASON_COUNT"] = 0
    totals["TOTAL_UNIQUE_TRADES_GLOBAL"] = int(global_unique) if isinstance(global_unique, int) else None
    totals["GLOBAL_UNIQUE_TRADE_IDENTITY_DIGEST"] = global_unique_digest
    totals["GLOBAL_UNIQUE_TRADES_COVERAGE_COMPLETE"] = bool(global_unique_complete)
    totals["TOTAL_UNIQUE_TRADES_COVERAGE_COMPLETE"] = (
        totals["TRADE_SHARDS_MISSING_EXACT_UNIQUE_COUNT"] == 0
        and global_unique_complete
    )

    if UNCOMPRESSED_PATCH.is_file():
        try:
            size_doc=json.loads(UNCOMPRESSED_PATCH.read_text(encoding="utf-8"))
            size_rows=size_doc.get("sizes") if isinstance(size_doc,dict) else {}
            if isinstance(size_rows,dict):
                total_uncompressed=sum(
                    int(row.get("uncompressed_bytes") or 0)
                    for row in size_rows.values()
                    if isinstance(row,dict)
                )
                totals["TOTAL_UNCOMPRESSED_BYTES"]=total_uncompressed
                totals["UNCOMPRESSED_SIZE_COVERAGE_COMPLETE"]=size_doc.get("coverage_complete") is True
                totals["UNCOMPRESSED_SIZE_PATCH_DIGEST"]=hashlib.sha256(
                    json.dumps(size_doc,sort_keys=True,separators=(",",":")).encode()
                ).hexdigest()
        except (OSError,ValueError,TypeError):
            totals["UNCOMPRESSED_SIZE_COVERAGE_COMPLETE"]=False

    totals["VALID_RECORD_COUNT_MISSING_SHARDS"] = valid_record_count_missing
    totals["UNIQUE_RECORD_COUNT_MISSING_SHARDS"] = unique_record_count_missing
    totals["VALID_RECORDS_COVERAGE_COMPLETE"] = (
        valid_record_count_missing == 0 and record_doc.get("coverage_complete") is True
    )
    totals["UNIQUE_RECORDS_COVERAGE_COMPLETE"] = (
        unique_record_count_missing == 0 and record_doc.get("coverage_complete") is True
    )
    totals["RECORD_COUNT_PATCH_DIGEST"] = (
        hashlib.sha256(json.dumps(record_doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if record_doc else None
    )
    totals["UNCOMPRESSED_SIZE_COVERAGE_COMPLETE"] = (
        totals["UNCOMPRESSED_SIZE_UNCLASSIFIED_ASSETS"] == 0
        and totals["UNCOMPRESSED_SIZE_UNAVAILABLE_ASSETS"] == 0
        and (
            totals["TOTAL_SHARDS"] == 0
            or totals["UNCOMPRESSED_SIZE_EXACT_ASSETS"] == totals["TOTAL_SHARDS"]
            or size_doc.get("coverage_complete") is True
        )
    )
    totals["UNCOMPRESSED_SIZE_PATCH_DIGEST"] = (
        hashlib.sha256(json.dumps(size_doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if size_doc else None
    )
    payload = {
        "schema_version": "alina.data_metrics.v4",
        "method": "verified_manifest_or_asset_scan_counts_no_byte_estimation",
        "source_index_sha256": hashlib.sha256(INDEX.read_bytes()).hexdigest(),
        "dataset_generation": idx.get("dataset_generation") or idx.get("generation") or "V2_FRESH",
        "totals": totals,
        "by_venue": dict(sorted(by_venue.items())),
        "by_symbol": dict(sorted(by_symbol.items())),
        "by_family": dict(sorted(by_family.items())),
        "notes": {
            "TOTAL_TRADES_COLLECTED": (
                "sum of shards whose trade_count_exact=true only; unknown legacy "
                "trade shards are excluded, never zero-filled"
            ),
            "TOTAL_UNIQUE_TRADES_WITHIN_SHARDS": (
                "deduplicated within each verified shard only; this is not a claim "
                "of global cross-shard uniqueness"
            ),
            "TOTAL_UNIQUE_TRADES_GLOBAL": (
                "published from deterministic manifest identity digests when coverage "
                "is complete, otherwise from TRADE_UNIQUE_COUNT_PATCH.json"
            ),
        },
    }
    METRICS.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    print(json.dumps(build()["totals"], sort_keys=True))
