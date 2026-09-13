"""TRAIN-only multi-asset Lead-Lag tape loading.

This module contains only recorded-data ingestion and normalization. It remains
strictly PAPER/READ-ONLY and never submits or enables real orders.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.backtesting.lead_lag_source_alignment import _lines, _wall_ms

TrainingRangesLoader = Callable[[str | Path, Sequence[str | Path]], tuple[list[tuple[int, int]], dict[str, Any]]]
RangePredicate = Callable[[int, Sequence[tuple[int, int]]], bool]


def load_multiasset_train_tape(
    root: str | Path,
    sources: Sequence[str | Path],
    *,
    coins: Sequence[str],
    default_candidate_coins: Sequence[str],
    training_ranges: TrainingRangesLoader,
    in_ranges: RangePredicate,
) -> tuple[dict[str, dict[str, list]], dict[str, Any]]:
    """Scan aligned Binance/Hyperliquid sources once for the frozen TRAIN span.

    ``BIN_TRADE`` and ``HL`` rows recorded in the same source share the local
    observable wall clock. Keeping both sides of that recording together avoids
    joining a dense Binance trade tape to an unrelated, sparse L2 tape.
    """

    project_root = Path(root).resolve()
    allowed = {str(coin).upper() for coin in coins}
    train_ranges, split_meta = training_ranges(project_root, sources)
    tapes: dict[str, list[tuple[int, float, float]]] = {coin: [] for coin in sorted(allowed)}
    trade_observations: dict[str, list[dict[str, Any]]] = {coin: [] for coin in sorted(allowed)}
    books: dict[str, list[dict[str, Any]]] = {coin: [] for coin in sorted(allowed)}
    source_ids = {coin: {"TRADE": set(), "HL_BOOK": set()} for coin in sorted(allowed)}
    seen_trades: set[tuple[Any, ...]] = set()
    seen_books: set[tuple[Any, ...]] = set()
    consumed: list[str] = []
    lines_read = invalid = outside_train = duplicates = 0
    book_invalid = book_outside_train = book_duplicates = 0

    for value in sources:
        path = Path(value)
        if not path.is_absolute():
            path = project_root / path
        path = path.resolve()
        if not path.is_file():
            continue
        source_id = path.relative_to(project_root).as_posix() if path.is_relative_to(project_root) else str(path)
        consumed.append(source_id)
        for line in _lines(path):
            lines_read += 1
            if "BIN_TRADE" not in line and '\"venue\":\"HL\"' not in line and '\"venue\": \"HL\"' not in line:
                continue
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                invalid += 1
                continue
            if not isinstance(row, Mapping):
                invalid += 1
                continue
            venue = str(row.get("venue") or "")
            coin = str(row.get("coin") or "").upper()
            if coin not in allowed:
                continue
            timestamp_ms = _wall_ms(dict(row))
            if venue == "HL":
                try:
                    bid = float(row.get("bid"))
                    ask = float(row.get("ask"))
                    bid_size = float(row.get("bid_sz", row.get("bid_size")))
                    ask_size = float(row.get("ask_sz", row.get("ask_size")))
                except (TypeError, ValueError, OverflowError):
                    bid = ask = bid_size = ask_size = 0.0
                if (
                    timestamp_ms is None
                    or not all(math.isfinite(number) for number in (bid, ask, bid_size, ask_size))
                    or bid <= 0.0
                    or ask < bid
                    or bid_size <= 0.0
                    or ask_size <= 0.0
                ):
                    book_invalid += 1
                    continue
                if not in_ranges(timestamp_ms, train_ranges):
                    book_outside_train += 1
                    continue
                identity = (
                    coin,
                    str(row.get("event_id") or ""),
                    int(timestamp_ms),
                    float(bid),
                    float(ask),
                    float(bid_size),
                    float(ask_size),
                )
                if identity in seen_books:
                    book_duplicates += 1
                    continue
                seen_books.add(identity)
                books[coin].append(
                    {
                        "coin": coin,
                        "ts_ms": int(timestamp_ms),
                        "received_ts_ms": row.get("recv_wall_ts_ms"),
                        "written_ts_ms": row.get("write_wall_ts_ms"),
                        "observable_at_ms": int(timestamp_ms),
                        "exchange_ts_ms": row.get("ts_ex"),
                        "bid": float(bid),
                        "ask": float(ask),
                        "bid_size": float(bid_size),
                        "ask_size": float(ask_size),
                        "bid_top_usd": float(bid) * float(bid_size),
                        "ask_top_usd": float(ask) * float(ask_size),
                        "bid_depth_usd": float(bid) * float(bid_size),
                        "ask_depth_usd": float(ask) * float(ask_size),
                        "connection_id": row.get("connection_id"),
                        "sequence": row.get("sequence"),
                        "feed_quality_score": row.get("feed_quality_score"),
                        "data_gate_ready": row.get("data_gate_ready"),
                        "event_id": row.get("event_id"),
                        "source_id": source_id,
                        "source": "hyperliquid:recorded:aligned_bbo",
                        "data_origin": "RECORDED_REAL",
                        "read_only": True,
                        "real_execution": False,
                    }
                )
                source_ids[coin]["HL_BOOK"].add(source_id)
                continue
            if venue != "BIN_TRADE":
                continue
            try:
                price = float(row.get("px"))
            except (TypeError, ValueError, OverflowError):
                price = 0.0
            if timestamp_ms is None or price <= 0.0:
                invalid += 1
                continue
            if not in_ranges(timestamp_ms, train_ranges):
                outside_train += 1
                continue
            side = str(row.get("side") or "").upper()
            direction = 1.0 if side == "BUY" else -1.0
            identity = (
                coin,
                str(row.get("event_id") or ""),
                int(timestamp_ms),
                float(price),
                direction,
                row.get("sz"),
            )
            if identity in seen_trades:
                duplicates += 1
                continue
            seen_trades.add(identity)
            tapes[coin].append((int(timestamp_ms) * 1_000_000, float(price), direction))
            trade_observations[coin].append(
                {"observable_at_ms": int(timestamp_ms), "price": float(price), "source_id": source_id}
            )
            source_ids[coin]["TRADE"].add(source_id)

    result: dict[str, dict[str, list]] = {}
    for coin, rows in tapes.items():
        rows.sort()
        trade_observations[coin].sort(
            key=lambda row: (int(row["observable_at_ms"]), str(row["source_id"]), float(row["price"]))
        )
        books[coin].sort(key=lambda row: int(row["ts_ms"]))
        if rows:
            result[coin] = {
                "HL": [],
                "BIN": [],
                "TRADE": rows,
                "TRADE_OBS": trade_observations[coin],
                "HL_BOOK": books[coin],
                "TRADE_SOURCE_IDS": sorted(source_ids[coin]["TRADE"]),
                "HL_BOOK_SOURCE_IDS": sorted(source_ids[coin]["HL_BOOK"]),
            }

    return result, {
        "schema_version": "hypersmart.lead_lag_multiasset_train_tape.v1",
        **split_meta,
        "candidate_coins": list(default_candidate_coins),
        "coins_with_train_trades": sorted(result),
        "sources_read": len(consumed),
        "sources": consumed,
        "lines_read": lines_read,
        "invalid_rows": invalid,
        "rows_outside_frozen_train": outside_train,
        "duplicates_rejected": duplicates,
        "hl_book_invalid_rows": book_invalid,
        "hl_book_rows_outside_frozen_train": book_outside_train,
        "hl_book_duplicates_rejected": book_duplicates,
        "lead_trades_by_coin": {coin: len(streams["TRADE"]) for coin, streams in result.items()},
        "hl_books_by_coin": {coin: len(streams["HL_BOOK"]) for coin, streams in result.items()},
        "hl_book_rows": sum(len(streams["HL_BOOK"]) for streams in result.values()),
        "hl_book_source": "ALIGNED_BBO_SAME_SHARD_CAUSAL",
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_loaded": False,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = ["load_multiasset_train_tape"]
