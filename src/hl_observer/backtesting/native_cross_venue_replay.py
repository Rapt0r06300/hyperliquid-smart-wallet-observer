"""Replay normalized native full-L2 snapshots across venues.

The scanner is an economic *prefilter*, never a PnL certification.  It searches
the recorded same-runner market tape for synchronized exact-depth dislocations,
charges venue-specific four-leg fee floors, and separately surfaces hypothetical
maker economics without pretending passive fills occurred.
"""
from __future__ import annotations

import gzip
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.arbitrage.multi_venue_execution import executable_pair_rows
from hl_observer.collection.native_venue_market import (
    DESYNC,
    UNMEASURABLE,
    MarketLevel,
    MultiVenueMarketStore,
    NativeMarketSnapshot,
)
from hl_observer.datasets.source_discovery import load_family_source_paths

SCHEMA_VERSION = "hypersmart.native_cross_venue_prefilter.v1"
DEFAULT_NOTIONAL_USD = 100.0
DEFAULT_NOTIONALS_USD = (50.0, 100.0, 250.0, 500.0)
DEFAULT_MAX_ROWS = 250_000
MAX_RECEIVE_SKEW_MS = 250.0
MAX_EXCHANGE_SKEW_MS = 250.0


def _lines(path: Path) -> Iterable[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8", errors="ignore") as handle:
            yield from handle
    except OSError:
        return


def _finite(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _integer(value: object) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _levels(raw: object) -> tuple[MarketLevel, ...]:
    if not isinstance(raw, list):
        return ()
    rows: list[MarketLevel] = []
    for item in raw:
        try:
            price = float(item[0])
            size = float(item[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if math.isfinite(price) and math.isfinite(size) and price > 0.0 and size > 0.0:
            rows.append(MarketLevel(price=price, size=size))
    return tuple(rows)


def snapshot_from_record(record: Mapping[str, Any]) -> NativeMarketSnapshot | None:
    """Rebuild one normalized snapshot without inventing missing depth."""
    if str(record.get("channel") or "") != "native_market":
        return None
    summary = record.get("parsed_summary")
    if not isinstance(summary, Mapping):
        return None
    venue = str(summary.get("venue") or "").strip().lower()
    coin = str(summary.get("coin") or record.get("instrument") or "").strip().upper()
    bid = _finite(summary.get("bid"))
    ask = _finite(summary.get("ask"))
    exchange_ts = _integer(summary.get("exchange_ts_ms", record.get("exchange_ts_ms")))
    receive_ts = _integer(summary.get("receive_ts_ms", record.get("received_ts_ms")))
    bids = _levels(summary.get("bids"))
    asks = _levels(summary.get("asks"))
    if (
        not venue
        or not coin
        or bid is None
        or ask is None
        or exchange_ts is None
        or receive_ts is None
        or not bids
        or not asks
    ):
        return None
    quality = str(summary.get("quality") or "")
    explicit_quality = quality if quality in {DESYNC, UNMEASURABLE} else None
    try:
        return NativeMarketSnapshot.build(
            venue=venue,
            coin=coin,
            exchange_symbol=str(summary.get("exchange_symbol") or coin),
            bid=bid,
            ask=ask,
            exchange_ts_ms=exchange_ts,
            receive_ts_ms=receive_ts,
            now_ms=receive_ts,
            stale_after_ms=1_000,
            quality=explicit_quality,
            bids=bids,
            asks=asks,
            sequence=_integer(summary.get("sequence")),
            update_id=_integer(summary.get("update_id")),
            connection_id=str(summary.get("connection_id") or record.get("connection_id") or "") or None,
            receive_mono_ns=_integer(summary.get("receive_mono_ns", record.get("local_monotonic_ns"))),
            transport_rtt_ms=_finite(summary.get("transport_rtt_ms")),
            clock_offset_ms=_finite(summary.get("clock_offset_ms")),
            gap_count=max(0, int(summary.get("gap_count") or record.get("gap_count") or 0)),
            duplicate_count=max(0, int(summary.get("duplicate_count") or 0)),
            regression_count=max(0, int(summary.get("regression_count") or 0)),
            reason=str(summary.get("reason") or ""),
        )
    except (TypeError, ValueError, OverflowError):
        return None


def load_native_market_snapshots(
    root: str | Path,
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> tuple[list[tuple[str, NativeMarketSnapshot]], dict[str, Any]]:
    project_root = Path(root).resolve()
    sources = [
        path
        for path in load_family_source_paths(project_root, "market_ticks")
        if "native_market" in {part.casefold() for part in path.parts}
    ]
    rows: list[tuple[str, NativeMarketSnapshot]] = []
    seen: set[tuple[str, str, int, int | None, str | None]] = set()
    lines_read = invalid = duplicates = 0
    truncated = False
    limit = max(0, int(max_rows))
    for path in sources:
        for line in _lines(path):
            lines_read += 1
            if '"native_market"' not in line:
                continue
            try:
                record = json.loads(line)
            except (TypeError, ValueError):
                invalid += 1
                continue
            if not isinstance(record, Mapping):
                invalid += 1
                continue
            snapshot = snapshot_from_record(record)
            summary = record.get("parsed_summary")
            clock_domain_id = (
                str(summary.get("clock_domain_id") or "").strip()
                if isinstance(summary, Mapping)
                else ""
            )
            if snapshot is None or not clock_domain_id:
                invalid += 1
                continue
            identity = (
                snapshot.venue,
                snapshot.coin,
                snapshot.receive_ts_ms,
                snapshot.sequence,
                snapshot.connection_id,
            )
            if identity in seen:
                duplicates += 1
                continue
            seen.add(identity)
            rows.append((clock_domain_id, snapshot))
            if limit > 0 and len(rows) > limit:
                truncated = True
                break
        if truncated:
            break
    rows.sort(
        key=lambda item: (
            item[0],
            int(item[1].receive_ts_ms),
            int(item[1].receive_mono_ns or 0),
            item[1].venue,
            item[1].coin,
        )
    )
    if truncated:
        rows = rows[:limit]
    return rows, {
        "sources": [str(path) for path in sources],
        "sources_read": len(sources),
        "lines_read": lines_read,
        "snapshot_rows": len(rows),
        "invalid_rows": invalid,
        "duplicates_rejected": duplicates,
        "max_rows": limit,
        "truncated": truncated,
        "paper_read_only": True,
        "real_execution": False,
    }


def scan_native_cross_venue_prefilter(
    root: str | Path,
    *,
    notional_usd: float | None = None,
    notionals_usd: Sequence[float] | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> dict[str, Any]:
    snapshots, input_audit = load_native_market_snapshots(root, max_rows=max_rows)
    requested_notionals = (
        (float(notional_usd),)
        if notional_usd is not None
        else tuple(float(value) for value in (notionals_usd or DEFAULT_NOTIONALS_USD))
    )
    if not requested_notionals or any(
        not math.isfinite(value) or value <= 0.0 for value in requested_notionals
    ):
        raise ValueError("notionals_usd must contain finite positive values")
    stores: dict[str, MultiVenueMarketStore] = {}
    seen_candidates: set[tuple[str, str, str, int, float]] = set()
    candidates: list[dict[str, Any]] = []
    pair_counts: Counter[str] = Counter()
    coin_counts: Counter[str] = Counter()
    taker_viable = buy_maker_viable = sell_maker_viable = both_maker_viable = 0

    for clock_domain_id, snapshot in snapshots:
        store = stores.setdefault(
            clock_domain_id,
            MultiVenueMarketStore(stale_after_ms=1_000),
        )
        store.put(snapshot)
        pairs = store.synchronized_pairs(
            snapshot.coin,
            now_ms=snapshot.receive_ts_ms,
            max_receive_skew_ms=MAX_RECEIVE_SKEW_MS,
            max_exchange_skew_ms=MAX_EXCHANGE_SKEW_MS,
            require_clock_offsets=False,
            require_l2=True,
        )
        for tested_notional in requested_notionals:
            rows = executable_pair_rows(
                pairs,
                notional_usd=float(tested_notional),
                minimum_round_trip_edge_bps=-1_000_000.0,
            )
            for row in rows:
                buy_snapshot = store.get(
                    str(row["buy_venue"]),
                    snapshot.coin,
                    now_ms=snapshot.receive_ts_ms,
                )
                sell_snapshot = store.get(
                    str(row["sell_venue"]),
                    snapshot.coin,
                    now_ms=snapshot.receive_ts_ms,
                )
                if buy_snapshot is None or sell_snapshot is None:
                    continue
                detected_at_ms = max(
                    int(buy_snapshot.receive_ts_ms),
                    int(sell_snapshot.receive_ts_ms),
                )
                identity = (
                    str(row["coin"]),
                    str(row["buy_venue"]),
                    str(row["sell_venue"]),
                    detected_at_ms,
                    float(tested_notional),
                )
                if identity in seen_candidates:
                    continue
                seen_candidates.add(identity)
                enriched = {
                    **row,
                    "detected_at_ms": detected_at_ms,
                    "tested_notional_usd": float(tested_notional),
                }
                candidates.append(enriched)
                pair = f"{row['buy_venue']}->{row['sell_venue']}"
                pair_counts[pair] += 1
                coin_counts[str(row["coin"])] += 1
                if float(row["taker_taker_round_trip_net_floor_bps"]) > 0.0:
                    taker_viable += 1
                if float(row["buy_maker_round_trip_net_floor_bps"]) > 0.0:
                    buy_maker_viable += 1
                if float(row["sell_maker_round_trip_net_floor_bps"]) > 0.0:
                    sell_maker_viable += 1
                if float(row["both_maker_round_trip_net_floor_bps"]) > 0.0:
                    both_maker_viable += 1

    ranked = sorted(
        candidates,
        key=lambda row: (
            max(
                float(row["taker_taker_round_trip_net_floor_bps"]),
                float(row["both_maker_round_trip_net_floor_bps"]),
            ),
            float(row["gross_executable_edge_bps"]),
        ),
        reverse=True,
    )
    top = ranked[:100]
    best_taker = max(
        (float(row["taker_taker_round_trip_net_floor_bps"]) for row in ranked),
        default=None,
    )
    best_both_maker = max(
        (float(row["both_maker_round_trip_net_floor_bps"]) for row in ranked),
        default=None,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "family": "cross_venue_dislocation_v2",
        "status": (
            "TRUNCATED_DIAGNOSTIC_ONLY"
            if input_audit["truncated"]
            else "COMPLETE_PREFILTER"
        ),
        "notionals_usd": list(requested_notionals),
        "input_audit": input_audit,
        "clock_domains": len(stores),
        "candidate_observations": len(ranked),
        "taker_taker_positive_fee_floor": taker_viable,
        "buy_maker_positive_fee_floor_unproven_fill": buy_maker_viable,
        "sell_maker_positive_fee_floor_unproven_fill": sell_maker_viable,
        "both_maker_positive_fee_floor_unproven_fill": both_maker_viable,
        "best_taker_taker_round_trip_net_floor_bps": best_taker,
        "best_both_maker_round_trip_net_floor_bps": best_both_maker,
        "pair_counts": dict(sorted(pair_counts.items())),
        "coin_counts": dict(sorted(coin_counts.items())),
        "top_candidates": top,
        "closed_cycle_proven": False,
        "maker_fill_proven": False,
        "economic_claim_eligible": False,
        "carry_pnl_usd": 0.0,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "DEFAULT_MAX_ROWS",
    "DEFAULT_NOTIONAL_USD",
    "DEFAULT_NOTIONALS_USD",
    "SCHEMA_VERSION",
    "load_native_market_snapshots",
    "scan_native_cross_venue_prefilter",
    "snapshot_from_record",
]
