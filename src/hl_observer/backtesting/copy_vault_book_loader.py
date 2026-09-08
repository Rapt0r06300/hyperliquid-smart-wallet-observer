"""Observed-book loader for the executable Copy-Vault replay.

Extracted from copy_vault_executable to keep the canonical strategy module
small enough to audit safely. No network access and no economic semantics are
changed here.
"""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# Keep this import-free from copy_vault_executable: that module re-exports this
# loader, so importing it here creates a circular import in a cold interpreter.
# Regression tests assert equality with the canonical protocol constants.
MAX_TARGET_LAG_MS = 30_000
CHECKPOINT_COLLECTOR_PROTOCOL = (
    "copy_vault_checkpoint_companion_v2_for_"
    "copy_vault_executable_walk_forward_v7_exact_checkpoint_binding"
)
CHECKPOINT_WRITER_STATE_SCHEMA = "hypersmart.copy_vault_checkpoint_tail.v2"
CHECKPOINT_INTEGRITY_SCHEMA = "hypersmart.copy_vault_checkpoint_integrity.v1"
CHECKPOINT_STATE_RELPATH = "runtime/data/copy_vault_checkpoint_tail_state.json"


def load_observed_books(
    root: str | Path,
    *,
    coins: Iterable[str] | None = None,
    relative_path: str = "runtime/data/carnet_venues.jsonl",
    causal_relative_path: str = "runtime/data/copy_vault_l2_tape.jsonl",
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Load historical books plus causally received Hyperliquid L2 samples."""

    resolved_root = Path(root).resolve()
    path = resolved_root / relative_path
    causal_path = resolved_root / causal_relative_path
    checkpoint_state_path = resolved_root / CHECKPOINT_STATE_RELPATH
    try:
        checkpoint_state = json.loads(checkpoint_state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        checkpoint_state = None
    writer_run_id = (
        str(checkpoint_state.get("writer_run_id") or "").strip()
        if isinstance(checkpoint_state, dict)
        else ""
    )
    try:
        clean_epoch_ms = int(checkpoint_state.get("clean_epoch_ms") or 0)
        output_start_offset = int(checkpoint_state.get("output_start_offset") or 0)
    except (AttributeError, TypeError, ValueError, OverflowError):
        clean_epoch_ms = 0
        output_start_offset = -1
    clean_epoch_receipt_valid = bool(
        isinstance(checkpoint_state, dict)
        and checkpoint_state.get("schema_version") == CHECKPOINT_WRITER_STATE_SCHEMA
        and checkpoint_state.get("protocol") == CHECKPOINT_COLLECTOR_PROTOCOL
        and checkpoint_state.get("paper_read_only") is True
        and checkpoint_state.get("real_execution") is False
        and writer_run_id
        and clean_epoch_ms > 0
        and output_start_offset >= 0
    )
    wanted = {str(coin).upper() for coin in coins} if coins is not None else None
    by_coin: dict[str, list[dict[str, Any]]] = {}
    invalid = 0
    rows_read = 0
    duplicate_rows = 0
    checkpoint_protocol_mismatches = 0
    duplicate_checkpoint_ids = 0
    duplicate_checkpoint_rows = 0
    quarantined_checkpoint_rows = 0
    quarantined_checkpoint_metaorders: set[str] = set()
    clean_checkpoint_counts: Counter[str] = Counter()
    clean_duplicated_ids: set[str] = set()
    clean_quarantined_metaorders: set[str] = set()
    seen: set[tuple[Any, ...]] = set()
    source_counts: dict[str, int] = {
        "historical_observed": 0,
        "causal_ws": 0,
        "causal_info_checkpoint": 0,
    }

    def add_row(
        *, coin: str, ts_ms: int, bid: float, ask: float, capacity_usd: float,
        source: str, source_line: int, causal_observation: bool,
        metaorder_id: str | None = None,
        checkpoint_stage: str | None = None,
        checkpoint_id: str | None = None,
        checkpoint_target_ms: int | None = None,
        collector_protocol: str | None = None,
        checkpoint_writer_run_id: str | None = None,
        checkpoint_clean_epoch_ms: int | None = None,
    ) -> None:
        nonlocal invalid, duplicate_rows
        if not coin or ts_ms <= 0 or bid <= 0 or ask <= bid or capacity_usd <= 0:
            invalid += 1
            return
        identity = (
            ("checkpoint", checkpoint_id)
            if checkpoint_id
            else ("book", coin, ts_ms, bid, ask, capacity_usd, causal_observation)
        )
        if identity in seen:
            duplicate_rows += 1
            return
        seen.add(identity)
        row = {
            "coin": coin,
            "ts_ms": ts_ms,
            "bid": bid,
            "ask": ask,
            "capacity_usd": capacity_usd,
            "source": source,
            "source_line": source_line,
            "causal_observation": causal_observation,
        }
        if checkpoint_id:
            row.update({
                "metaorder_id": metaorder_id,
                "checkpoint_stage": checkpoint_stage,
                "checkpoint_id": checkpoint_id,
                "checkpoint_target_ms": checkpoint_target_ms,
                "collector_protocol": collector_protocol,
                "writer_run_id": checkpoint_writer_run_id,
                "clean_epoch_ms": checkpoint_clean_epoch_ms,
            })
        by_coin.setdefault(coin, []).append(row)
        if not causal_observation:
            source_counts["historical_observed"] += 1
        elif source == "HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT":
            source_counts["causal_info_checkpoint"] += 1
        else:
            source_counts["causal_ws"] += 1

    if path.is_file():
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line_number, line in enumerate(handle, 1):
                rows_read += 1
                try:
                    raw = json.loads(line)
                    coin = str(raw.get("coin") or "").upper()
                    if wanted is not None and coin not in wanted:
                        continue
                    add_row(
                        coin=coin,
                        ts_ms=int(round(float(raw["collecte_ts"]) * 1000.0)),
                        bid=float(raw["hl_bid"]),
                        ask=float(raw["hl_ask"]),
                        capacity_usd=float(raw["taille_min_usd"]),
                        source=relative_path,
                        source_line=line_number,
                        causal_observation=False,
                    )
                except (KeyError, TypeError, ValueError, OverflowError, json.JSONDecodeError):
                    invalid += 1
    if causal_path.is_file():
        checkpoint_counts: Counter[str] = Counter()
        checkpoint_metaorders: dict[str, set[str]] = {}
        clean_checkpoint_metaorders: dict[str, set[str]] = {}
        with causal_path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                try:
                    raw = json.loads(line)
                    coin = str(raw.get("coin") or "").upper()
                    if wanted is not None and coin not in wanted:
                        continue
                    checkpoint_id = str(raw.get("checkpoint_id") or "").strip()
                    if not checkpoint_id:
                        continue
                    metaorder_id = str(raw.get("metaorder_id") or "").strip()
                    checkpoint_stage = str(raw.get("checkpoint_stage") or "").strip()
                    collector_protocol = str(raw.get("collector_protocol") or "").strip()
                    received = int(raw["received_at_ms"])
                    exchange_ts = int(raw["exchange_ts_ms"])
                    checkpoint_target_ms = int(raw["checkpoint_target_ms"])
                    bid = float(raw["bid"])
                    ask = float(raw["ask"])
                    capacity_usd = float(raw["capacity_usd"])
                    if not (
                        collector_protocol == CHECKPOINT_COLLECTOR_PROTOCOL
                        and metaorder_id
                        and checkpoint_stage
                        and checkpoint_target_ms > 0
                        and raw.get("schema_version") == "hypersmart.copy_vault_l2.v1"
                        and raw.get("source") in {
                            "HYPERLIQUID_L2_WS",
                            "HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT",
                        }
                        and raw.get("data_origin") == "REAL_OBSERVED"
                        and raw.get("causal_observation") is True
                        and received >= exchange_ts > 0
                        and received - exchange_ts <= MAX_TARGET_LAG_MS
                        and coin
                        and bid > 0
                        and ask > bid
                        and capacity_usd > 0
                    ):
                        continue
                    checkpoint_counts[checkpoint_id] += 1
                    checkpoint_metaorders.setdefault(checkpoint_id, set()).add(metaorder_id)
                    row_writer_run_id = str(raw.get("writer_run_id") or "").strip()
                    row_clean_epoch_ms = int(raw.get("clean_epoch_ms") or 0)
                    if (
                        clean_epoch_receipt_valid
                        and row_writer_run_id == writer_run_id
                        and row_clean_epoch_ms == clean_epoch_ms
                        and received >= clean_epoch_ms
                    ):
                        clean_checkpoint_counts[checkpoint_id] += 1
                        clean_checkpoint_metaorders.setdefault(checkpoint_id, set()).add(
                            metaorder_id
                        )
                except (KeyError, TypeError, ValueError, OverflowError, json.JSONDecodeError):
                    continue
        duplicated_ids = {
            checkpoint_id
            for checkpoint_id, count in checkpoint_counts.items()
            if count > 1
        }
        duplicate_checkpoint_ids = len(duplicated_ids)
        duplicate_checkpoint_rows = sum(
            checkpoint_counts[checkpoint_id] - 1
            for checkpoint_id in duplicated_ids
        )
        quarantined_checkpoint_metaorders = {
            metaorder_id
            for checkpoint_id in duplicated_ids
            for metaorder_id in checkpoint_metaorders[checkpoint_id]
        }
        clean_duplicated_ids = {
            checkpoint_id
            for checkpoint_id in duplicated_ids
            if checkpoint_id in clean_checkpoint_counts
        }
        clean_quarantined_metaorders = {
            metaorder_id
            for checkpoint_id in clean_duplicated_ids
            for metaorder_id in clean_checkpoint_metaorders[checkpoint_id]
        }
        duplicate_rows += duplicate_checkpoint_rows

        with causal_path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line_number, line in enumerate(handle, 1):
                rows_read += 1
                try:
                    raw = json.loads(line)
                    coin = str(raw.get("coin") or "").upper()
                    if wanted is not None and coin not in wanted:
                        continue
                    received = int(raw["received_at_ms"])
                    exchange_ts = int(raw["exchange_ts_ms"])
                    allowed_source = raw.get("source") in {
                        "HYPERLIQUID_L2_WS",
                        "HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT",
                    }
                    checkpoint_id = str(raw.get("checkpoint_id") or "").strip() or None
                    is_checkpoint = (
                        checkpoint_id is not None
                        or raw.get("source") == "HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT"
                    )
                    metaorder_id = str(raw.get("metaorder_id") or "").strip() or None
                    checkpoint_stage = (
                        str(raw.get("checkpoint_stage") or "").strip() or None
                    )
                    collector_protocol = (
                        str(raw.get("collector_protocol") or "").strip() or None
                    )
                    checkpoint_target_ms = (
                        int(raw["checkpoint_target_ms"]) if is_checkpoint else None
                    )
                    checkpoint_binding_valid = (
                        not is_checkpoint
                        or (
                            collector_protocol == CHECKPOINT_COLLECTOR_PROTOCOL
                            and bool(metaorder_id)
                            and bool(checkpoint_stage)
                            and bool(checkpoint_id)
                            and checkpoint_target_ms is not None
                            and checkpoint_target_ms > 0
                        )
                    )
                    if not checkpoint_binding_valid:
                        checkpoint_protocol_mismatches += 1
                        invalid += 1
                        continue
                    causal = (
                        raw.get("schema_version") == "hypersmart.copy_vault_l2.v1"
                        and allowed_source
                        and raw.get("data_origin") == "REAL_OBSERVED"
                        and raw.get("causal_observation") is True
                        and received >= exchange_ts > 0
                        and received - exchange_ts <= MAX_TARGET_LAG_MS
                    )
                    if not causal:
                        invalid += 1
                        continue
                    if is_checkpoint and metaorder_id in quarantined_checkpoint_metaorders:
                        quarantined_checkpoint_rows += 1
                        continue
                    add_row(
                        coin=coin,
                        ts_ms=received,
                        bid=float(raw["bid"]),
                        ask=float(raw["ask"]),
                        capacity_usd=float(raw["capacity_usd"]),
                        source=str(raw["source"]),
                        source_line=line_number,
                        causal_observation=True,
                        metaorder_id=metaorder_id,
                        checkpoint_stage=checkpoint_stage,
                        checkpoint_id=checkpoint_id,
                        checkpoint_target_ms=checkpoint_target_ms,
                        collector_protocol=collector_protocol,
                        checkpoint_writer_run_id=(
                            str(raw.get("writer_run_id") or "").strip() or None
                        ),
                        checkpoint_clean_epoch_ms=(
                            int(raw.get("clean_epoch_ms") or 0) or None
                        ),
                    )
                except (KeyError, TypeError, ValueError, OverflowError, json.JSONDecodeError):
                    invalid += 1
    for rows in by_coin.values():
        rows.sort(key=lambda row: row["ts_ms"])
    valid = sum(len(rows) for rows in by_coin.values())
    return by_coin, {
        "sources": [relative_path, causal_relative_path],
        "exists": path.is_file() or causal_path.is_file(),
        "rows_read": rows_read,
        "valid_rows": valid,
        "invalid_rows": invalid,
        "duplicate_rows_rejected": duplicate_rows,
        "duplicate_checkpoint_ids": duplicate_checkpoint_ids,
        "duplicate_checkpoint_rows": duplicate_checkpoint_rows,
        "quarantined_checkpoint_metaorders": len(quarantined_checkpoint_metaorders),
        "quarantined_checkpoint_rows": quarantined_checkpoint_rows,
        "clean_epoch_receipt": {
            "schema_version": CHECKPOINT_INTEGRITY_SCHEMA,
            "receipt_valid": clean_epoch_receipt_valid,
            "writer_role": "BOUND_WRITER" if clean_epoch_receipt_valid else None,
            "writer_run_id": writer_run_id or None,
            "clean_epoch_ms": clean_epoch_ms or None,
            "output_start_offset": output_start_offset if output_start_offset >= 0 else None,
            "checkpoint_rows": sum(clean_checkpoint_counts.values()),
            "duplicate_checkpoint_ids": len(clean_duplicated_ids),
            "quarantined_checkpoint_metaorders": len(clean_quarantined_metaorders),
        },
        "checkpoint_protocol_mismatches_rejected": checkpoint_protocol_mismatches,
        "coins": len(by_coin),
        "source_counts": source_counts,
        "causal_forward_rows": (
            source_counts["causal_ws"] + source_counts["causal_info_checkpoint"]
        ),
        "capacity_semantics": "minimum_USD_across_HL_and_reference_venue_bid_ask",
    }


__all__ = [
    "CHECKPOINT_COLLECTOR_PROTOCOL",
    "MAX_TARGET_LAG_MS",
    "load_observed_books",
]
