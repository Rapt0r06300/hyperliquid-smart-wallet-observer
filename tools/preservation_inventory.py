#!/usr/bin/env python3
"""Read-only, fail-closed inventory of the canonical Alina preservation corpus.

Reports exactly what is indexed, what is eligible for SAFE replay restoration,
and what must remain quarantined for later repair. Never downloads or deletes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.partitioned_data_index import read_index
except ModuleNotFoundError:
    from partitioned_data_index import read_index

REPO = Path(__file__).resolve().parents[1]
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
STATUSES = {"SAFE", "PARTIAL", "REJECT", "STALE", "NO_DATA"}


class InventoryError(ValueError):
    """Insufficient or contradictory evidence: never certify coverage."""


def summarize(index: Mapping[str, Any], metrics: Mapping[str, Any], index_digest: str) -> dict[str, Any]:
    rows = index.get("shards")
    totals = metrics.get("totals")
    if not isinstance(rows, list) or not isinstance(totals, Mapping):
        raise InventoryError("catalog/metrics missing verified shard list or totals")
    if (metrics.get("source_index_sha256") != index_digest
            or metrics.get("schema_version") != "alina.data_metrics.v4"
            or type(totals.get("TOTAL_SHARDS")) is not int
            or totals["TOTAL_SHARDS"] != len(rows)):
        raise InventoryError("DATA_METRICS does not match canonical DATA_INDEX")

    counts: Counter[str] = Counter()
    by_family: dict[str, Counter[str]] = defaultdict(Counter)
    seen_ids: set[str] = set()
    outer: dict[tuple[str, str], tuple[int, str]] = {}
    replay_shards = 0
    replay_logical_bytes = 0
    safe_not_replayable = 0
    recoverable_unknown = 0
    for row in rows:
        if not isinstance(row, Mapping):
            raise InventoryError("invalid shard row")
        ident = row.get("dataset_id")
        if not isinstance(ident, str) or not ident or ident in seen_ids:
            raise InventoryError("duplicate or missing dataset_id")
        seen_ids.add(ident)
        status = row.get("quality_status")
        if status not in STATUSES:
            raise InventoryError(f"unrecognized quality_status for {ident}")
        family = row.get("family")
        if not isinstance(family, str) or not family:
            raise InventoryError(f"missing family for {ident}")
        counts[status] += 1
        by_family[family][status] += 1
        if status in ("PARTIAL", "REJECT", "STALE"):
            # These are investigation candidates, NOT proven recoverable bytes.
            recoverable_unknown += 1
        if status != "SAFE":
            continue
        if row.get("replay_compatible") is not True:
            safe_not_replayable += 1
            continue
        tag = row.get("release_tag")
        member = row.get("release_asset")
        container = row.get("release_container_asset")
        logical_size = row.get("bytes")
        digest = row.get("sha256")
        if (not isinstance(tag, str) or not tag
                or not isinstance(member, str) or not member
                or type(logical_size) is not int or logical_size < 0
                or not isinstance(digest, str) or not SHA256.fullmatch(digest.lower())):
            raise InventoryError(f"SAFE replayable shard has incomplete identity: {ident}")
        if container:
            if not isinstance(container, str):
                raise InventoryError(f"invalid packed asset reference: {ident}")
            outer_size = row.get("release_remote_size")
            outer_digest = str(row.get("release_remote_digest") or "").removeprefix("sha256:").lower()
            key = (tag, container)
        else:
            outer_size = logical_size
            outer_digest = digest.lower()
            key = (tag, member)
        if (type(outer_size) is not int or outer_size < 0
                or not SHA256.fullmatch(outer_digest)):
            raise InventoryError(f"missing SHA-256/size for Release asset: {ident}")
        evidence = (outer_size, outer_digest)
        if key in outer and outer[key] != evidence:
            raise InventoryError(f"conflicting immutable Release asset: {key}")
        outer[key] = evidence
        replay_shards += 1
        replay_logical_bytes += logical_size

    # Deduplicate packed ZIPs: a single outer asset may hold many SAFE shards.
    result = {
        "schema": "alina.preservation_inventory.v1",
        "status": "CATALOG_CLASSIFIED_NOT_RESTORED",
        "catalog_index_sha256": index_digest,
        "indexed_shards": len(rows),
        "quality_counts": {k: counts[k] for k in sorted(STATUSES)},
        "safe_replayable_shards": replay_shards,
        "safe_non_replayable_shards": safe_not_replayable,
        "replay_required_unique_assets": len(outer),
        "replay_required_download_bytes": sum(size for size, _ in outer.values()),
        "replay_shard_compressed_logical_bytes": replay_logical_bytes,
        "unresolved_unsafe_shards": recoverable_unknown,
        "by_family": {name: dict(sorted(c.items())) for name, c in sorted(by_family.items())},
        "global_trade_uniqueness_certified": totals.get("GLOBAL_UNIQUE_TRADES_COVERAGE_COMPLETE") is True,
        "all_exploitable_data_restored": False,
        "recovered_partial_shards": None,
        "definitively_irrecoverable_shards": None,
        "notes": [
            "Catalog classification is not byte-level restoration certification.",
            "PARTIAL, STALE and REJECT remain preserved for evidence-based review; never delete on this report.",
            "Ancillary SAFE market data (L2/BBO/capacity/tickers) is included even if it has zero trades.",
            "Never promote an unsafe shard without a new immutable manifest and strict validation.",
        ],
    }
    if replay_shards != counts["SAFE"]:
        result["status"] = "INCOMPLETE_SAFE_REPLAY_COVERAGE"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=REPO / "catalog/DATA_INDEX.json")
    parser.add_argument("--metrics", type=Path, default=REPO / "catalog/DATA_METRICS.json")
    args = parser.parse_args(argv)
    try:
        raw = args.index.read_bytes()
        index = read_index(args.index)
        metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
        report = summarize(index, metrics, hashlib.sha256(raw).hexdigest())
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "INVENTORY_INCOMPLETE", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "CATALOG_CLASSIFIED_NOT_RESTORED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
