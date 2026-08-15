"""Observed-book loader for the executable Copy-Vault replay.

Extracted from copy_vault_executable to keep the canonical strategy module
small enough to audit safely. No network access and no economic semantics are
changed here.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from hl_observer.backtesting import copy_vault_executable as _base


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
    wanted = {str(coin).upper() for coin in coins} if coins is not None else None
    by_coin: dict[str, list[dict[str, Any]]] = {}
    invalid = 0
    rows_read = 0
    duplicate_rows = 0
    seen: set[tuple[Any, ...]] = set()
    source_counts: dict[str, int] = {
        "historical_observed": 0,
        "causal_ws": 0,
        "causal_info_checkpoint": 0,
    }

    def add_row(
        *, coin: str, ts_ms: int, bid: float, ask: float, capacity_usd: float,
        source: str, source_line: int, causal_observation: bool,
    ) -> None:
        nonlocal invalid, duplicate_rows
        if not coin or ts_ms <= 0 or bid <= 0 or ask <= bid or capacity_usd <= 0:
            invalid += 1
            return
        identity = (coin, ts_ms, bid, ask, capacity_usd, causal_observation)
        if identity in seen:
            duplicate_rows += 1
            return
        seen.add(identity)
        by_coin.setdefault(coin, []).append({
            "coin": coin,
            "ts_ms": ts_ms,
            "bid": bid,
            "ask": ask,
            "capacity_usd": capacity_usd,
            "source": source,
            "source_line": source_line,
            "causal_observation": causal_observation,
        })
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
                    causal = (
                        raw.get("schema_version") == "hypersmart.copy_vault_l2.v1"
                        and allowed_source
                        and raw.get("data_origin") == "REAL_OBSERVED"
                        and raw.get("causal_observation") is True
                        and received >= exchange_ts > 0
                        and received - exchange_ts <= _base.MAX_TARGET_LAG_MS
                    )
                    if not causal:
                        invalid += 1
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
        "coins": len(by_coin),
        "source_counts": source_counts,
        "causal_forward_rows": (
            source_counts["causal_ws"] + source_counts["causal_info_checkpoint"]
        ),
        "capacity_semantics": "minimum_USD_across_HL_and_reference_venue_bid_ask",
    }
