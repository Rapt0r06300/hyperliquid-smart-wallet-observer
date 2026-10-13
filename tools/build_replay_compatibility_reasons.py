#!/usr/bin/env python3
"""Build deterministic, trade-weighted explanations for replay compatibility gaps."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.partitioned_data_index import read_index
except ModuleNotFoundError:
    from partitioned_data_index import read_index

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "catalog" / "DATA_INDEX.json"
OUTPUT = ROOT / "catalog" / "REPLAY_COMPATIBILITY_REASONS.json"
TRADE_FAMILIES = {"trades", "agg_trades", "fills", "userfills", "user_fills", "copy_vault_fills"}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _exact_trade_count(row: Mapping[str, Any]) -> int:
    if str(row.get("family") or "").lower() not in TRADE_FAMILIES:
        return 0
    if row.get("trade_count_exact") is not True:
        return 0
    try:
        value = int(row.get("trade_count") or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, value)


def _blocking_reasons(row: Mapping[str, Any]) -> list[str]:
    # Most SAFE/replayable shards do not need a per-shard manifest read.
    if row.get("replay_compatible") is True:
        return []
    reasons = row.get("quality_reasons")
    if not isinstance(reasons, list):
        reasons = None
    if reasons is None:
        path = ROOT / str(row.get("manifest_path") or "")
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            manifest = {}
        candidate = manifest.get("quality_reasons") if isinstance(manifest, Mapping) else None
        reasons = candidate if isinstance(candidate, list) else []
    normalized = sorted({str(x) for x in reasons if str(x)})
    if normalized:
        return normalized
    replay_reason = str(row.get("replay_reason") or "").strip()
    return [replay_reason or "REPLAY_COMPATIBILITY_NOT_PROVEN"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()

    index = read_index(INDEX)
    rows = index.get("shards") or []
    primary_counts: Counter[str] = Counter()
    blocker_shards: Counter[str] = Counter()
    blocker_trades: Counter[str] = Counter()
    # Repeating every classification in a second Git-tracked JSON file grows
    # beyond GitHub\u0027s 100 MiB blob limit while adding no unique evidence.
    # Original per-shard identities and reasons remain in the SHA-bound index
    # and immutable manifest receipts; this report contains exact aggregates.
    row_count = 0
    safe_not_replayable = 0
    replayable_not_safe = 0
    non_replayable_trades = 0
    replayable_trades = 0

    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("REPLAY_REASONS_INVALID_CANONICAL_SHARD_ROW")
        row_count += 1
        status = str(row.get("quality_status") or "UNKNOWN")
        replay = row.get("replay_compatible") is True
        trades = _exact_trade_count(row)
        blockers = _blocking_reasons(row)

        if status == "SAFE" and replay:
            primary = "SAFE_REPLAY_COMPATIBLE"
        elif status != "SAFE" and replay:
            primary = f"REPLAYABLE_BUT_{status}"
        elif blockers:
            primary = blockers[0]
        elif status == "SAFE":
            primary = "REPLAY_COMPATIBILITY_NOT_PROVEN"
        else:
            primary = f"NOT_SAFE_OR_REPLAYABLE:{status}"

        primary_counts[primary] += 1
        if status == "SAFE" and not replay:
            safe_not_replayable += 1
        if status != "SAFE" and replay:
            replayable_not_safe += 1
        if replay:
            replayable_trades += trades
        else:
            non_replayable_trades += trades
            for reason in blockers or [primary]:
                blocker_shards[reason] += 1
                blocker_trades[reason] += trades

    body = {
        "schema": "alina.replay_compatibility_reasons.v3",
        "classification_source": "SHA_BOUND_CANONICAL_DATA_INDEX_AND_IMMUTABLE_MANIFESTS",
        "classifications_materialized": False,
        "source_index_sha256": hashlib.sha256(INDEX.read_bytes()).hexdigest(),
        "row_count": row_count,
        "reason_counts": dict(sorted(primary_counts.items())),
        "blocking_reason_shard_counts": dict(sorted(blocker_shards.items())),
        "blocking_reason_trade_counts": dict(sorted(blocker_trades.items())),
        "blocking_reason_trade_counts_overlap": True,
        "replayable_trade_count_exact": replayable_trades,
        "non_replayable_trade_count_exact": non_replayable_trades,
        "safe_not_replayable_count": safe_not_replayable,
        "replayable_not_safe_count": replayable_not_safe,
    }
    body["receipt_digest"] = hashlib.sha256(canonical(body).encode()).hexdigest()
    encoded = (json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    # Fail closed rather than retry five GitHub pushes of a >100 MiB blob.
    if len(encoded) >= 8 * 1024 * 1024:
        raise ValueError("REPLAY_REASONS_AGGREGATES_EXCEED_8MIB")
    target = Path(args.output)
    tmp = target.with_name(target.name + ".partial")
    tmp.write_bytes(encoded)
    tmp.replace(target)
    print(json.dumps({
        "row_count": body["row_count"],
        "replayable_trade_count_exact": replayable_trades,
        "non_replayable_trade_count_exact": non_replayable_trades,
        "safe_not_replayable_count": body["safe_not_replayable_count"],
        "replayable_not_safe_count": body["replayable_not_safe_count"],
        "receipt_digest": body["receipt_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
