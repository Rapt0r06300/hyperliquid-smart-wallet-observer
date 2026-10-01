#!/usr/bin/env python3
"""Freeze one discovered market universe into deterministic replay-grade shards."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _owner(coin: str, shard_count: int) -> int:
    key = str(coin).strip().upper().encode("utf-8")
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % shard_count


def freeze_market_shards(
    *,
    plan_path: Path,
    output_dir: Path,
    shard_count: int,
    index_output: Path,
) -> dict[str, Any]:
    if shard_count < 1:
        raise ValueError("shard_count must be >= 1")
    raw_bytes = plan_path.read_bytes()
    payload = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("market plan must be a JSON object")
    selected = [
        dict(row)
        for row in payload.get("selected", [])
        if isinstance(row, Mapping) and str(row.get("coin") or "").strip()
    ]
    if not selected:
        raise ValueError("market plan contains no selected coins")

    coins = [str(row["coin"]).strip().upper() for row in selected]
    if len(coins) != len(set(coins)):
        raise ValueError("market plan contains duplicate canonical coins")

    universe_digest = _sha256_bytes(raw_bytes)
    buckets: list[list[dict[str, Any]]] = [[] for _ in range(shard_count)]
    for row in selected:
        buckets[_owner(str(row["coin"]), shard_count)].append(row)

    output_dir.mkdir(parents=True, exist_ok=True)
    shard_rows: list[dict[str, Any]] = []
    covered: list[str] = []
    for index, assigned in enumerate(buckets):
        if not assigned:
            continue
        assigned.sort(key=lambda row: str(row["coin"]).strip().upper())
        covered.extend(str(row["coin"]).strip().upper() for row in assigned)
        shard_payload = {
            "schema": "alina.cloud_collection_plan.v1",
            "plan_role": "replay_grade_market_shard",
            "source_schema": payload.get("schema"),
            "universe_digest": universe_digest,
            "market_shard_assignment": "sha256_coin_mod",
            "market_shard_count": shard_count,
            "market_shard_index": index,
            "full_selected_coin_count": len(selected),
            "selected_coin_count": len(assigned),
            "min_venues": payload.get("min_venues"),
            "venue_market_counts": payload.get("venue_market_counts") or {},
            "errors": payload.get("errors") or {},
            "selected": assigned,
            "coins": assigned,
            "read_only": True,
            "real_execution": False,
        }
        shard_path = output_dir / f"shard-{index:02d}.json"
        rendered = (
            json.dumps(shard_payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8")
        shard_path.write_bytes(rendered)
        shard_rows.append(
            {
                "market_shard_index": index,
                "plan_file": shard_path.as_posix(),
                "plan_sha256": _sha256_bytes(rendered),
                "selected_coin_count": len(assigned),
            }
        )

    if sorted(covered) != sorted(coins) or len(covered) != len(set(covered)):
        raise ValueError("frozen market shards do not form an exact disjoint cover")

    index_payload = {
        "schema": "alina.market_shard_index.v1",
        "universe_digest": universe_digest,
        "source_plan_file": plan_path.as_posix(),
        "market_shard_count": shard_count,
        "non_empty_shard_count": len(shard_rows),
        "full_selected_coin_count": len(selected),
        "market_shard_assignment": "sha256_coin_mod",
        "shards": shard_rows,
        "read_only": True,
        "real_execution": False,
    }
    index_output.parent.mkdir(parents=True, exist_ok=True)
    index_output.write_text(
        json.dumps(index_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return index_payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--index-output", required=True)
    args = parser.parse_args()
    result = freeze_market_shards(
        plan_path=Path(args.plan),
        output_dir=Path(args.output_dir),
        shard_count=int(args.shard_count),
        index_output=Path(args.index_output),
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
