"""Strict Cross-Venue certification primitives (paper/read-only).

This module is deliberately independent from profitability selection. It
certifies whether an observed HL/Binance snapshot and a synthetic two-leg
round-trip are technically eligible for economic evidence.

Legacy carnet rows are preserved but never upgraded: without an exact
instrument mapping, per-venue receive timestamps, bounded venue skew and raw
depth, they remain diagnostic only.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.config.cross_venue_instruments import (
    ATOMIC_BBO_SOURCE_MODE,
    MAPPING_SCHEMA_VERSION,
    mapping_record,
)

SOURCE_MODE = "CERTIFIED_ATOMIC_FOUR_SIDE_BOOK_V2"
BBO_SOURCE_MODE = ATOMIC_BBO_SOURCE_MODE
FOUR_FILL_CONTRACT_VERSION = "cross_four_fill_aon_v1"
MAX_VENUE_SKEW_MS = 250.0
MAX_SNAPSHOT_AGE_MS = 3_000.0
MAX_INTERLEG_OBSERVATION_SKEW_MS = 250.0
MAX_SPREAD_BPS = 100.0
DEFAULT_MAX_HOLDING_MS = 4 * 60 * 60 * 1000.0
DEFAULT_MAX_OBSERVATION_GAP_MS = 300_000.0


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _normalize_levels(values: object, *, side: str) -> list[tuple[float, float]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return []
    rows: list[tuple[float, float]] = []
    for item in values:
        try:
            price = float(item[0])
            size = float(item[1])
        except (TypeError, ValueError, IndexError, KeyError):
            if isinstance(item, Mapping):
                try:
                    price = float(item["px"])
                    size = float(item["sz"])
                except (TypeError, ValueError, KeyError):
                    continue
            else:
                continue
        if not (math.isfinite(price) and math.isfinite(size) and price > 0 and size > 0):
            continue
        rows.append((price, size))
    rows.sort(key=lambda row: row[0], reverse=side == "BID")
    return rows


def spread_bps(bids: object, asks: object) -> float | None:
    bid_rows = _normalize_levels(bids, side="BID")
    ask_rows = _normalize_levels(asks, side="ASK")
    if not bid_rows or not ask_rows or ask_rows[0][0] <= bid_rows[0][0]:
        return None
    mid = (bid_rows[0][0] + ask_rows[0][0]) / 2.0
    return (ask_rows[0][0] - bid_rows[0][0]) / mid * 10_000.0 if mid > 0 else None


def vwap_for_notional(levels: object, notional_usd: float, *, side: str) -> dict[str, Any]:
    """Consume depth for a marketable fill without inventing missing liquidity."""
    requested = _number(notional_usd)
    rows = _normalize_levels(levels, side="ASK" if side.upper() == "BUY" else "BID")
    if requested is None or requested <= 0 or not rows:
        return {
            "complete": False,
            "requested_notional_usd": requested,
            "filled_notional_usd": 0.0,
            "vwap": None,
            "levels_used": 0,
            "remaining_notional_usd": requested,
        }
    remaining = requested
    filled = quantity = cost = 0.0
    used = 0
    for price, size in rows:
        available_notional = price * size
        take_notional = min(remaining, available_notional)
        if take_notional <= 0:
            continue
        take_qty = take_notional / price
        filled += take_notional
        quantity += take_qty
        cost += take_qty * price
        remaining -= take_notional
        used += 1
        if remaining <= 1e-9:
            break
    complete = remaining <= max(1e-8, requested * 1e-10)
    return {
        "complete": complete,
        "requested_notional_usd": requested,
        "filled_notional_usd": round(filled, 10),
        "vwap": round(cost / quantity, 12) if quantity > 0 else None,
        "levels_used": used,
        "remaining_notional_usd": round(max(0.0, remaining), 10),
    }


def _received_ms(row: Mapping[str, Any], venue: str) -> float | None:
    return _number(row.get(f"{venue}_received_at_ms"))


def certify_atomic_row(row: Mapping[str, Any], *, max_skew_ms: float = MAX_VENUE_SKEW_MS) -> dict[str, Any]:
    reasons: list[str] = []
    mapping = mapping_record(row.get("coin"), row.get("binance_symbol"))
    if mapping["exact"] is not True:
        reasons.append("INSTRUMENT_MAPPING_NOT_EXACT")
    hl_received = _received_ms(row, "hl")
    bin_received = _received_ms(row, "bin")
    if hl_received is None or bin_received is None:
        reasons.append("VENUE_RECEIVE_TIMESTAMPS_MISSING")
        skew = None
    else:
        skew = abs(bin_received - hl_received)
        if skew > float(max_skew_ms):
            reasons.append("VENUE_SKEW_TOO_HIGH")
    books: dict[str, dict[str, list[tuple[float, float]]]] = {}
    for venue, prefix in (("HL", "hl"), ("BIN", "bin")):
        bids = _normalize_levels(row.get(f"{prefix}_bids5"), side="BID")
        asks = _normalize_levels(row.get(f"{prefix}_asks5"), side="ASK")
        books[venue] = {"bids": bids, "asks": asks}
        current_spread = spread_bps(bids, asks)
        if current_spread is None:
            reasons.append(f"{venue}_BOOK_INVALID")
        elif current_spread > MAX_SPREAD_BPS:
            reasons.append(f"{venue}_SPREAD_TOO_WIDE")
    snapshot_ts = max(value for value in (hl_received, bin_received) if value is not None) if (
        hl_received is not None or bin_received is not None
    ) else None
    capacity_values: list[float] = []
    top_level_capacity_values: list[float] = []
    for venue in ("HL", "BIN"):
        for side in ("bids", "asks"):
            levels = books[venue][side]
            if levels:
                capacity_values.append(sum(price * size for price, size in levels))
                top_level_capacity_values.append(levels[0][0] * levels[0][1])
    min_capacity = min(capacity_values) if len(capacity_values) == 4 else None
    min_top_level_capacity = (
        min(top_level_capacity_values)
        if len(top_level_capacity_values) == 4
        else None
    )
    declared_capacity = _number(row.get("taille_min_usd"))
    if min_capacity is None or min_capacity <= 0:
        reasons.append("FOUR_SIDE_DEPTH_MISSING")
    elif declared_capacity is not None and declared_capacity > min_capacity + max(0.01, min_capacity * 1e-8):
        reasons.append("DECLARED_CAPACITY_EXCEEDS_RAW_DEPTH")
    if row.get("read_only") is not True or row.get("real_execution") is not False:
        reasons.append("NOT_READ_ONLY_PROVENANCE")
    return {
        "ok": not reasons,
        "reasons": sorted(set(reasons)),
        "source_mode": SOURCE_MODE,
        "mapping": mapping,
        "mapping_verified": mapping["exact"] is True,
        "skew_ms": round(skew, 6) if skew is not None else None,
        "skew_verified": skew is not None and skew <= float(max_skew_ms),
        "max_venue_skew_ms": float(max_skew_ms),
        "snapshot_ts_ms": snapshot_ts,
        "hl_received_at_ms": hl_received,
        "bin_received_at_ms": bin_received,
        "books": books,
        "minimum_four_side_capacity_usd": round(min_capacity, 8) if min_capacity is not None else None,
        "minimum_top_level_capacity_usd": (
            round(min_top_level_capacity, 8)
            if min_top_level_capacity is not None
            else None
        ),
        "four_fill_contract_version": FOUR_FILL_CONTRACT_VERSION,
        "paper_read_only": True,
        "real_execution": False,
    }


def certify_atomic_bbo_row(
    row: Mapping[str, Any],
    *,
    max_skew_ms: float = MAX_VENUE_SKEW_MS,
    max_age_ms: float = 750.0,
) -> dict[str, Any]:
    """Certify a dense BBO row without upgrading incomplete legacy rows."""

    reasons: list[str] = []
    if row.get("source_mode") != BBO_SOURCE_MODE or row.get("atomic_bbo_certified") is not True:
        reasons.append("EXPLICIT_ATOMIC_BBO_PROVENANCE_MISSING")
    mapping = mapping_record(row.get("coin"), row.get("binance_symbol"))
    if mapping["exact"] is not True:
        reasons.append("INSTRUMENT_MAPPING_NOT_EXACT")
    if row.get("instrument_mapping_schema") != MAPPING_SCHEMA_VERSION:
        reasons.append("INSTRUMENT_MAPPING_SCHEMA_MISSING")
    if row.get("instrument_mapping_exact") is not True:
        reasons.append("INSTRUMENT_MAPPING_ASSERTION_MISSING")

    hl_received = _number(row.get("hl_received_at_ms") or row.get("recv_wall_hl_ms"))
    bin_received = _number(row.get("bin_received_at_ms") or row.get("recv_wall_bin_ms"))
    hl_mono = _number(row.get("recu_mono_hl_ns"))
    bin_mono = _number(row.get("recu_mono_bin_ns"))
    if hl_received is None or bin_received is None:
        reasons.append("VENUE_RECEIVE_TIMESTAMPS_MISSING")
    if hl_mono is None or bin_mono is None:
        reasons.append("MONOTONIC_RECEIVE_TIMESTAMPS_MISSING")
        skew = None
    else:
        skew = abs(hl_mono - bin_mono) / 1_000_000.0
        if skew > float(max_skew_ms):
            reasons.append("VENUE_SKEW_TOO_HIGH")
    declared_skew = _number(row.get("desync_ms"))
    if skew is None or declared_skew is None or abs(declared_skew - skew) > 0.011:
        reasons.append("VENUE_SKEW_NOT_RECONCILED")

    age_hl = _number(row.get("age_hl_ms"))
    age_bin = _number(row.get("age_bin_ms"))
    if any(age is None or age < 0.0 or age > float(max_age_ms) for age in (age_hl, age_bin)):
        reasons.append("BBO_NOT_FRESH")

    prices = {
        "hl_bid": _number(row.get("hl_bid")),
        "hl_ask": _number(row.get("hl_ask")),
        "bin_bid": _number(row.get("bin_bid")),
        "bin_ask": _number(row.get("bin_ask")),
    }
    sizes = {
        "hl_bid_sz": _number(row.get("hl_bid_sz")),
        "hl_ask_sz": _number(row.get("hl_ask_sz")),
        "bin_bid_sz": _number(row.get("bin_bid_sz")),
        "bin_ask_sz": _number(row.get("bin_ask_sz")),
    }
    if any(value is None or value <= 0.0 for value in (*prices.values(), *sizes.values())):
        reasons.append("FOUR_SIDE_BBO_MISSING")
    if prices["hl_bid"] is not None and prices["hl_ask"] is not None and prices["hl_ask"] <= prices["hl_bid"]:
        reasons.append("HL_BOOK_INVALID")
    if prices["bin_bid"] is not None and prices["bin_ask"] is not None and prices["bin_ask"] <= prices["bin_bid"]:
        reasons.append("BIN_BOOK_INVALID")

    capacity = None
    if not any(value is None or value <= 0.0 for value in (*prices.values(), *sizes.values())):
        capacity = min(
            float(prices["hl_bid"]) * float(sizes["hl_bid_sz"]),
            float(prices["hl_ask"]) * float(sizes["hl_ask_sz"]),
            float(prices["bin_bid"]) * float(sizes["bin_bid_sz"]),
            float(prices["bin_ask"]) * float(sizes["bin_ask_sz"]),
        )
    declared_capacity = _number(row.get("minimum_four_side_top_capacity_usd"))
    compatibility_capacity = _number(row.get("taille_top_usd"))
    tolerance = max(1e-6, (capacity or 0.0) * 1e-8)
    if capacity is None or declared_capacity is None or compatibility_capacity is None:
        reasons.append("FOUR_SIDE_CAPACITY_PROOF_MISSING")
    elif abs(declared_capacity - capacity) > tolerance or abs(compatibility_capacity - capacity) > tolerance:
        reasons.append("FOUR_SIDE_CAPACITY_NOT_RECONCILED")
    if row.get("read_only") is not True or row.get("real_execution") is not False:
        reasons.append("NOT_READ_ONLY_PROVENANCE")
    snapshot_ts_ms = _number(row.get("snapshot_wall_ts_ms") or row.get("ts_ms"))
    if snapshot_ts_ms is None:
        reasons.append("SNAPSHOT_TIMESTAMP_MISSING")

    books = {
        "HL": {
            "bids": [(prices["hl_bid"], sizes["hl_bid_sz"])] if prices["hl_bid"] and sizes["hl_bid_sz"] else [],
            "asks": [(prices["hl_ask"], sizes["hl_ask_sz"])] if prices["hl_ask"] and sizes["hl_ask_sz"] else [],
        },
        "BIN": {
            "bids": [(prices["bin_bid"], sizes["bin_bid_sz"])] if prices["bin_bid"] and sizes["bin_bid_sz"] else [],
            "asks": [(prices["bin_ask"], sizes["bin_ask_sz"])] if prices["bin_ask"] and sizes["bin_ask_sz"] else [],
        },
    }
    return {
        "ok": not reasons,
        "reasons": sorted(set(reasons)),
        "source_mode": BBO_SOURCE_MODE,
        "mapping": mapping,
        "mapping_verified": mapping["exact"] is True,
        "skew_ms": round(skew, 6) if skew is not None else None,
        "skew_verified": skew is not None and skew <= float(max_skew_ms),
        "max_venue_skew_ms": float(max_skew_ms),
        "max_snapshot_age_ms": float(max_age_ms),
        "snapshot_ts_ms": snapshot_ts_ms,
        "hl_received_at_ms": hl_received,
        "bin_received_at_ms": bin_received,
        "books": books,
        "minimum_top_level_capacity_usd": round(capacity, 8) if capacity is not None else None,
        "four_fill_contract_version": FOUR_FILL_CONTRACT_VERSION,
        "paper_read_only": True,
        "real_execution": False,
    }


def load_certified_atomic_series(root: str | Path, *, coins: Sequence[str] | None = None, max_skew_ms: float = MAX_VENUE_SKEW_MS) -> tuple[dict[str, list[tuple]], dict[str, list[tuple[float, float]]], dict[str, Any]]:
    project_root = Path(root).resolve()
    source = project_root / "runtime/data/carnet_venues.jsonl"
    allowed = {str(coin).upper() for coin in coins} if coins else None
    series: dict[str, list[tuple]] = {}
    depth: dict[str, list[tuple[float, float]]] = {}
    seen: set[tuple[str, float, str]] = set()
    counters = {
        "lines_read": 0,
        "certified_snapshots": 0,
        "legacy_uncertified_rows_rejected": 0,
        "invalid_rows": 0,
        "duplicates_rejected": 0,
    }
    try:
        handle = source.open("r", encoding="utf-8", errors="ignore")
    except OSError:
        handle = None
    if handle is not None:
        with handle:
            for line in handle:
                counters["lines_read"] += 1
                try:
                    row = json.loads(line)
                except (TypeError, ValueError):
                    counters["invalid_rows"] += 1
                    continue
                coin = str(row.get("coin") or "").upper()
                if allowed is not None and coin not in allowed:
                    continue
                proof = certify_atomic_row(row, max_skew_ms=max_skew_ms)
                if not proof["ok"]:
                    counters["legacy_uncertified_rows_rejected"] += 1
                    continue
                ts = float(proof["snapshot_ts_ms"])
                observation_id = str(row.get("observation_id") or "")
                key = (coin, ts, observation_id)
                if key in seen:
                    counters["duplicates_rejected"] += 1
                    continue
                seen.add(key)
                books = proof["books"]
                hb, ha = books["HL"]["bids"][0][0], books["HL"]["asks"][0][0]
                bb, ba = books["BIN"]["bids"][0][0], books["BIN"]["asks"][0][0]
                # The replay settles at the recorded BBO.  Only liquidity on
                # the first level proves that this exact price can fill the
                # complete notional without inventing incremental slippage.
                capacity = float(proof["minimum_top_level_capacity_usd"])
                series.setdefault(coin, []).append((ts, "ATOMIC", hb, ha, bb, ba))
                depth.setdefault(coin, []).append((ts, capacity))
                counters["certified_snapshots"] += 1
    for rows in series.values():
        rows.sort()
    for rows in depth.values():
        rows.sort()
    return series, depth, {
        "source": "runtime/data/carnet_venues.jsonl",
        "source_mode": SOURCE_MODE,
        **counters,
        "coins": len(series),
        "mapping_verified": counters["certified_snapshots"] > 0,
        "skew_verified": counters["certified_snapshots"] > 0,
        "max_venue_skew_ms": float(max_skew_ms),
        "four_fill_contract_version": FOUR_FILL_CONTRACT_VERSION,
        "capacity_definition": "minimum USD capacity on the four BBO top levels",
        "legacy_rows_never_upgraded": True,
        "paper_read_only": True,
        "real_execution": False,
    }


def load_certified_atomic_bbo_series(
    root: str | Path,
    *,
    coins: Sequence[str] | None = None,
    max_skew_ms: float = MAX_VENUE_SKEW_MS,
) -> tuple[dict[str, list[tuple]], dict[str, list[tuple[float, float]]], dict[str, Any]]:
    """Load only explicitly certified high-frequency BBO rows."""

    project_root = Path(root).resolve()
    source = project_root / "runtime/data/cross_venue_atomic_bbo.jsonl"
    allowed = {str(coin).upper() for coin in coins} if coins else None
    series: dict[str, list[tuple]] = {}
    depth: dict[str, list[tuple[float, float]]] = {}
    seen: set[str] = set()
    counters = {
        "lines_read": 0,
        "certified_snapshots": 0,
        "legacy_uncertified_rows_rejected": 0,
        "invalid_rows": 0,
        "duplicates_rejected": 0,
    }
    try:
        handle = source.open("r", encoding="utf-8", errors="ignore")
    except OSError:
        handle = None
    if handle is not None:
        with handle:
            for line in handle:
                counters["lines_read"] += 1
                try:
                    row = json.loads(line)
                except (TypeError, ValueError):
                    counters["invalid_rows"] += 1
                    continue
                coin = str(row.get("coin") or "").upper()
                if allowed is not None and coin not in allowed:
                    continue
                proof = certify_atomic_bbo_row(row, max_skew_ms=max_skew_ms)
                if not proof["ok"]:
                    counters["legacy_uncertified_rows_rejected"] += 1
                    continue
                event_id = str(row.get("event_id") or "")
                if not event_id or event_id in seen:
                    counters["duplicates_rejected"] += 1
                    continue
                seen.add(event_id)
                ts = float(proof["snapshot_ts_ms"])
                books = proof["books"]
                hb, ha = books["HL"]["bids"][0][0], books["HL"]["asks"][0][0]
                bb, ba = books["BIN"]["bids"][0][0], books["BIN"]["asks"][0][0]
                capacity = float(proof["minimum_top_level_capacity_usd"])
                series.setdefault(coin, []).append((ts, "ATOMIC_BBO", hb, ha, bb, ba))
                depth.setdefault(coin, []).append((ts, capacity))
                counters["certified_snapshots"] += 1
    for rows in series.values():
        rows.sort()
    for rows in depth.values():
        rows.sort()
    return series, depth, {
        "source": "runtime/data/cross_venue_atomic_bbo.jsonl",
        "source_mode": BBO_SOURCE_MODE,
        **counters,
        "coins": len(series),
        "mapping_verified": counters["certified_snapshots"] > 0,
        "skew_verified": counters["certified_snapshots"] > 0,
        "max_venue_skew_ms": float(max_skew_ms),
        "four_fill_contract_version": FOUR_FILL_CONTRACT_VERSION,
        "capacity_definition": "minimum USD capacity on the four raw BBO sides",
        "legacy_rows_never_upgraded": True,
        "paper_read_only": True,
        "real_execution": False,
    }


def load_preferred_certified_atomic_series(
    root: str | Path,
    *,
    coins: Sequence[str] | None = None,
) -> tuple[dict[str, list[tuple]], dict[str, list[tuple[float, float]]], dict[str, Any]]:
    """Prefer event-driven BBO evidence once available, otherwise retain L2."""

    bbo_series, bbo_depth, bbo_meta = load_certified_atomic_bbo_series(root, coins=coins)
    if int(bbo_meta.get("certified_snapshots") or 0) > 0:
        return bbo_series, bbo_depth, bbo_meta
    book_series, book_depth, book_meta = load_certified_atomic_series(root, coins=coins)
    book_meta["preferred_bbo_source"] = bbo_meta
    return book_series, book_depth, book_meta


def snapshot_fresh(snapshot_ts_ms: object, now_ms: object, *, max_age_ms: float = MAX_SNAPSHOT_AGE_MS) -> bool:
    snapshot = _number(snapshot_ts_ms)
    now = _number(now_ms)
    return bool(snapshot is not None and now is not None and 0.0 <= now - snapshot <= float(max_age_ms))


def observation_gap_ok(previous_ts_ms: object, current_ts_ms: object, *, max_gap_ms: float = DEFAULT_MAX_OBSERVATION_GAP_MS) -> bool:
    previous = _number(previous_ts_ms)
    current = _number(current_ts_ms)
    return bool(previous is not None and current is not None and current >= previous and current - previous <= float(max_gap_ms))


def _fill(cert: Mapping[str, Any], *, venue: str, side: str, stage: str, notional_usd: float) -> dict[str, Any]:
    levels_key = "asks" if side == "BUY" else "bids"
    result = vwap_for_notional(cert["books"][venue][levels_key], notional_usd, side=side)
    return {"venue": venue, "side": side, "stage": stage, **result}


def build_four_fill_cycle(entry: Mapping[str, Any], exit_: Mapping[str, Any], *, direction: int, notional_usd: float, fees_bps_total: float, max_holding_ms: float = DEFAULT_MAX_HOLDING_MS, max_interleg_ms: float = MAX_INTERLEG_OBSERVATION_SKEW_MS) -> dict[str, Any]:
    """Build an all-or-none four-fill paper cycle from certified snapshots."""
    reasons: list[str] = []
    if entry.get("ok") is not True:
        reasons.append("ENTRY_SNAPSHOT_UNCERTIFIED")
    if exit_.get("ok") is not True:
        reasons.append("EXIT_SNAPSHOT_UNCERTIFIED")
    if entry.get("mapping", {}).get("hl_coin") != exit_.get("mapping", {}).get("hl_coin"):
        reasons.append("INSTRUMENT_CHANGED")
    try:
        direction_i = 1 if int(direction) > 0 else -1 if int(direction) < 0 else 0
    except (TypeError, ValueError):
        direction_i = 0
    if direction_i == 0:
        reasons.append("INVALID_DIRECTION")
    requested = _number(notional_usd)
    fees = _number(fees_bps_total)
    if requested is None or requested <= 0:
        reasons.append("INVALID_NOTIONAL")
    if fees is None or fees < 0:
        reasons.append("INVALID_FEES")
    entry_ts = _number(entry.get("snapshot_ts_ms"))
    exit_ts = _number(exit_.get("snapshot_ts_ms"))
    holding_ms = exit_ts - entry_ts if entry_ts is not None and exit_ts is not None else None
    if holding_ms is None or holding_ms < 0:
        reasons.append("NON_CAUSAL_EXIT")
    elif holding_ms > float(max_holding_ms):
        reasons.append("MAX_HOLDING_EXCEEDED")
    entry_skew = _number(entry.get("skew_ms"))
    exit_skew = _number(exit_.get("skew_ms"))
    if entry_skew is None or exit_skew is None:
        reasons.append("INTERLEG_OBSERVATION_SKEW_UNMEASURABLE")
    elif max(entry_skew, exit_skew) > float(max_interleg_ms):
        reasons.append("INTERLEG_OBSERVATION_SKEW_TOO_HIGH")

    plan = (
        (("HL", "SELL", "ENTRY"), ("BIN", "BUY", "ENTRY"), ("HL", "BUY", "EXIT"), ("BIN", "SELL", "EXIT"))
        if direction_i > 0
        else (("HL", "BUY", "ENTRY"), ("BIN", "SELL", "ENTRY"), ("HL", "SELL", "EXIT"), ("BIN", "BUY", "EXIT"))
    )
    fills: list[dict[str, Any]] = []
    if requested is not None and requested > 0 and not {"ENTRY_SNAPSHOT_UNCERTIFIED", "EXIT_SNAPSHOT_UNCERTIFIED"}.intersection(reasons):
        for venue, side, stage in plan:
            cert = entry if stage == "ENTRY" else exit_
            fills.append(_fill(cert, venue=venue, side=side, stage=stage, notional_usd=requested))
    incomplete = [index for index, fill in enumerate(fills) if fill.get("complete") is not True]
    if incomplete:
        reasons.append("PARTIAL_OR_MISSED_LEG")
    if len(fills) != 4:
        reasons.append("FOUR_FILL_CYCLE_INCOMPLETE")
    complete_four = len(fills) == 4 and not incomplete

    gross_usd = fees_usd = net_usd = None
    if complete_four and not reasons and requested is not None and fees is not None:
        e_hl, e_bin, x_hl, x_bin = fills
        if direction_i > 0:
            gross_usd = requested * (e_hl["vwap"] - x_hl["vwap"]) / e_hl["vwap"] + requested * (x_bin["vwap"] - e_bin["vwap"]) / e_bin["vwap"]
        else:
            gross_usd = requested * (x_hl["vwap"] - e_hl["vwap"]) / e_hl["vwap"] + requested * (e_bin["vwap"] - x_bin["vwap"]) / e_bin["vwap"]
        fees_usd = 2.0 * requested * fees / 10_000.0
        net_usd = gross_usd - fees_usd
    identity = "|".join((str(entry.get("mapping", {}).get("hl_coin")), str(entry_ts), str(exit_ts), str(direction_i), str(requested), FOUR_FILL_CONTRACT_VERSION))
    entry_basis = exit_basis = None
    try:
        entry_hl_mid = (entry["books"]["HL"]["bids"][0][0] + entry["books"]["HL"]["asks"][0][0]) / 2
        entry_bin_mid = (entry["books"]["BIN"]["bids"][0][0] + entry["books"]["BIN"]["asks"][0][0]) / 2
        exit_hl_mid = (exit_["books"]["HL"]["bids"][0][0] + exit_["books"]["HL"]["asks"][0][0]) / 2
        exit_bin_mid = (exit_["books"]["BIN"]["bids"][0][0] + exit_["books"]["BIN"]["asks"][0][0]) / 2
        entry_basis = (entry_hl_mid - entry_bin_mid) / ((entry_hl_mid + entry_bin_mid) / 2) * 1e4
        exit_basis = (exit_hl_mid - exit_bin_mid) / ((exit_hl_mid + exit_bin_mid) / 2) * 1e4
    except (KeyError, IndexError, TypeError, ZeroDivisionError):
        reasons.append("BASIS_UNMEASURABLE")
    converged = entry_basis is not None and exit_basis is not None and abs(exit_basis) < abs(entry_basis)
    return {
        "schema_version": FOUR_FILL_CONTRACT_VERSION,
        "trade_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "economic_eligible": not reasons and complete_four,
        "reasons": sorted(set(reasons)),
        "four_fills_complete": complete_four,
        "fill_count": len(fills),
        "fills": fills,
        "requested_notional_usd": requested,
        "fees_bps_total": fees,
        "gross_pnl_usd": round(gross_usd, 10) if gross_usd is not None else None,
        "fees_usd": round(fees_usd, 10) if fees_usd is not None else None,
        "net_pnl_usd": round(net_usd, 10) if net_usd is not None else None,
        "holding_ms": holding_ms,
        "entry_interleg_observation_skew_ms": entry_skew,
        "exit_interleg_observation_skew_ms": exit_skew,
        "naked_leg_risk": not complete_four,
        "partial_fill_detected": bool(incomplete),
        "entry_basis_bps": round(entry_basis, 8) if entry_basis is not None else None,
        "exit_basis_bps": round(exit_basis, 8) if exit_basis is not None else None,
        "converged": converged,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "BBO_SOURCE_MODE",
    "DEFAULT_MAX_HOLDING_MS",
    "DEFAULT_MAX_OBSERVATION_GAP_MS",
    "FOUR_FILL_CONTRACT_VERSION",
    "MAX_INTERLEG_OBSERVATION_SKEW_MS",
    "MAX_SNAPSHOT_AGE_MS",
    "MAX_SPREAD_BPS",
    "MAX_VENUE_SKEW_MS",
    "SOURCE_MODE",
    "build_four_fill_cycle",
    "certify_atomic_bbo_row",
    "certify_atomic_row",
    "load_certified_atomic_bbo_series",
    "load_certified_atomic_series",
    "load_preferred_certified_atomic_series",
    "observation_gap_ok",
    "snapshot_fresh",
    "spread_bps",
    "vwap_for_notional",
]
