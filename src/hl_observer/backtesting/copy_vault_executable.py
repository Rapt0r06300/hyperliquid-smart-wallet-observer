"""Causal, executable Copy-Vault paper replay.

The replay consumes canonical leader fills and observed Hyperliquid books.  It
does not interpolate prices, manufacture liquidity, or call an exchange.  A
paper episode exists only when a fresh reference, delayed entry, and later exit
are all observable and top-book capacity covers the configured notional.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hl_observer.config.frais_venues import frais_taker_bps

SCHEMA_VERSION = "hypersmart.copy_vault_executable.v1"
PROTOCOL_NAME = "copy_vault_executable_walk_forward_v3"
METAORDER_GAP_MS = 60_000
COPY_DELAY_MS = 60_000
MAX_REFERENCE_LAG_MS = 30_000
MAX_TARGET_LAG_MS = 30_000
HORIZONS_MS = (300_000, 900_000, 1_800_000, 3_600_000)
NOTIONAL_USD = 150.0
MAX_OPEN_POSITIONS = 6
MIN_TRAIN_TRADES = 8
TRAIN_FRACTION = 0.60
VALIDATION_FRACTION = 0.20


def protocol_signature() -> dict[str, Any]:
    return {
        "calibration_protocol": PROTOCOL_NAME,
        "metaorder_gap_ms": METAORDER_GAP_MS,
        "copy_delay_ms": COPY_DELAY_MS,
        "max_reference_lag_ms": MAX_REFERENCE_LAG_MS,
        "max_target_lag_ms": MAX_TARGET_LAG_MS,
        "horizons_ms": list(HORIZONS_MS),
        "notional_usd": NOTIONAL_USD,
        "max_open_positions": MAX_OPEN_POSITIONS,
        "fee_source": "hl_observer.config.frais_venues:frais_taker_bps(HL)",
        "book_source": (
            "train_oos=runtime/data/carnet_venues.jsonl;"
            "forward=runtime/data/copy_vault_l2_tape.jsonl:HYPERLIQUID_L2_WS_causal"
        ),
        "fill_source": "REST_BACKFILL_for_train_oos;LIVE_WS_non_snapshot_with_receive_time_for_forward",
        "forward_signal_policy": "causal_live_first_fill_observed_after_physical_freeze",
    }


def _event_identity(row: Mapping[str, Any]) -> str:
    existing = str(row.get("event_id") or row.get("fill_id") or "").strip()
    if existing:
        return existing
    material = (
        str(row.get("vault") or ""),
        int(row.get("ts_ms") or 0),
        str(row.get("coin") or "").upper(),
        int(row.get("direction") or 0),
        str(row.get("oid") or ""),
        str(row.get("hash") or ""),
        float(row.get("taille_usd") or 0.0),
    )
    return hashlib.sha256(repr(material).encode("utf-8")).hexdigest()


def cluster_metaorders(
    entries: Iterable[Mapping[str, Any]], *, gap_ms: int = METAORDER_GAP_MS
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collapse sliced fills without using later slices as independent trades.

    Clusters are maintained per vault/coin/direction, so interleaved fills from
    other markets do not accidentally split one leader metaorder.  The paper
    signal timestamp is the first observable fill; aggregate size is audit-only
    and is never used as a hindsight entry threshold.
    """

    canonical: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicate_events = 0
    for raw in entries:
        try:
            ts_ms = int(raw.get("ts_ms") or 0)
            direction = int(raw.get("direction") or 0)
            coin = str(raw.get("coin") or "").upper()
            vault = str(raw.get("vault") or "")
        except (TypeError, ValueError, OverflowError):
            continue
        if ts_ms <= 0 or direction not in (-1, 1) or not coin or not vault:
            continue
        event_id = _event_identity(raw)
        if event_id in seen:
            duplicate_events += 1
            continue
        seen.add(event_id)
        observed_at_ms: int | None = None
        try:
            candidate = int(raw.get("observed_at_ms") or 0)
            if candidate >= ts_ms:
                observed_at_ms = candidate
        except (TypeError, ValueError, OverflowError):
            pass
        causal_live = (
            raw.get("source") == "LIVE_WS"
            and raw.get("is_snapshot") is False
            and observed_at_ms is not None
        )
        canonical.append({
            **dict(raw),
            "event_id": event_id,
            "ts_ms": ts_ms,
            "observed_at_ms": observed_at_ms,
            "causal_forward_eligible": causal_live,
            "direction": direction,
            "coin": coin,
            "vault": vault,
        })
    canonical.sort(key=lambda row: (row["ts_ms"], row["event_id"]))

    active: dict[tuple[str, str, int], dict[str, Any]] = {}
    completed: list[dict[str, Any]] = []
    for row in canonical:
        key = (row["vault"], row["coin"], row["direction"])
        cluster = active.get(key)
        if cluster is None or row["ts_ms"] - cluster["last_fill_ts_ms"] > int(gap_ms):
            if cluster is not None:
                completed.append(cluster)
            cluster = {
                "vault": row["vault"],
                "coin": row["coin"],
                "direction": row["direction"],
                "first_fill_ts_ms": row["ts_ms"],
                "signal_ts_ms": (
                    row["observed_at_ms"]
                    if row["causal_forward_eligible"]
                    else row["ts_ms"]
                ),
                "signal_source": row.get("source") or "REST_BACKFILL",
                "causal_forward_eligible": row["causal_forward_eligible"],
                "last_fill_ts_ms": row["ts_ms"],
                "fill_count": 0,
                "leader_notional_usd": 0.0,
                "move_frac_audit_sum": 0.0,
                "member_event_ids": [],
            }
            active[key] = cluster
        cluster["last_fill_ts_ms"] = row["ts_ms"]
        cluster["fill_count"] += 1
        cluster["leader_notional_usd"] += max(0.0, float(row.get("taille_usd") or 0.0))
        cluster["move_frac_audit_sum"] += max(0.0, float(row.get("move_frac") or 0.0))
        cluster["member_event_ids"].append(row["event_id"])
    completed.extend(active.values())

    for cluster in completed:
        material = {
            "vault": cluster["vault"],
            "coin": cluster["coin"],
            "direction": cluster["direction"],
            "signal_ts_ms": cluster["signal_ts_ms"],
            "member_event_ids": cluster["member_event_ids"],
        }
        cluster["metaorder_id"] = hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        cluster["leader_notional_usd"] = round(cluster["leader_notional_usd"], 8)
        cluster["move_frac_audit_sum"] = round(cluster["move_frac_audit_sum"], 10)
    completed.sort(key=lambda row: (row["signal_ts_ms"], row["metaorder_id"]))
    return completed, {
        "input_events": len(canonical) + duplicate_events,
        "canonical_events": len(canonical),
        "duplicate_events_rejected": duplicate_events,
        "metaorders": len(completed),
        "sliced_fills_collapsed": max(0, len(canonical) - len(completed)),
        "signal_policy": "first_fill;later_slices_audit_only",
        "causal_forward_metaorders": sum(
            1 for row in completed if row.get("causal_forward_eligible") is True
        ),
    }


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
    source_counts: dict[str, int] = {"historical_observed": 0, "causal_ws": 0}

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
        source_counts["causal_ws" if causal_observation else "historical_observed"] += 1

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
                    causal = (
                        raw.get("schema_version") == "hypersmart.copy_vault_l2.v1"
                        and raw.get("source") == "HYPERLIQUID_L2_WS"
                        and raw.get("data_origin") == "REAL_OBSERVED"
                        and raw.get("causal_observation") is True
                        and received >= exchange_ts > 0
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
                        source=causal_relative_path,
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
        "causal_forward_rows": source_counts["causal_ws"],
        "capacity_semantics": "minimum_USD_across_HL_and_reference_venue_bid_ask",
    }


def _first_at_or_after(
    rows: list[dict[str, Any]], target_ms: int, max_lag_ms: int
) -> tuple[dict[str, Any] | None, int | None]:
    timestamps = [int(row["ts_ms"]) for row in rows]
    index = bisect.bisect_left(timestamps, int(target_ms))
    if index >= len(rows):
        return None, None
    lag = int(rows[index]["ts_ms"]) - int(target_ms)
    return (rows[index], lag) if 0 <= lag <= int(max_lag_ms) else (None, lag)


def execute_metaorder(
    metaorder: Mapping[str, Any],
    books: list[dict[str, Any]],
    *,
    horizon_ms: int,
    direction_multiplier: int = 1,
    copy_delay_ms: int = COPY_DELAY_MS,
    max_reference_lag_ms: int = MAX_REFERENCE_LAG_MS,
    max_target_lag_ms: int = MAX_TARGET_LAG_MS,
    notional_usd: float = NOTIONAL_USD,
    fee_bps: float | None = None,
    require_causal_books: bool = False,
) -> tuple[dict[str, Any] | None, str]:
    """Execute one closed paper episode or return an explicit refusal code."""

    if not books:
        return None, "NO_OBSERVED_BOOK_FOR_COIN"
    signal_ms = int(metaorder["signal_ts_ms"])
    reference, reference_lag = _first_at_or_after(
        books, signal_ms, max_reference_lag_ms
    )
    if reference is None:
        return None, "STALE_OR_MISSING_REFERENCE_BOOK"
    entry_target_ms = signal_ms + int(copy_delay_ms)
    entry, entry_lag = _first_at_or_after(books, entry_target_ms, max_target_lag_ms)
    if entry is None:
        return None, "STALE_OR_MISSING_ENTRY_BOOK"
    exit_target_ms = int(entry["ts_ms"]) + int(horizon_ms)
    exit_book, exit_lag = _first_at_or_after(books, exit_target_ms, max_target_lag_ms)
    if exit_book is None:
        return None, "STALE_OR_MISSING_EXIT_BOOK"
    causal_books = all(
        row.get("causal_observation") is True
        for row in (reference, entry, exit_book)
    )
    if require_causal_books and not causal_books:
        return None, "NON_CAUSAL_FORWARD_BOOK"
    if min(float(entry["capacity_usd"]), float(exit_book["capacity_usd"])) < float(notional_usd):
        return None, "OBSERVED_TOP_CAPACITY_TOO_LOW"

    direction = int(metaorder["direction"]) * (1 if int(direction_multiplier) >= 0 else -1)
    if direction not in (-1, 1):
        return None, "INVALID_DIRECTION"
    entry_mid = (float(entry["bid"]) + float(entry["ask"])) / 2.0
    exit_mid = (float(exit_book["bid"]) + float(exit_book["ask"])) / 2.0
    reference_mid = (float(reference["bid"]) + float(reference["ask"])) / 2.0
    entry_exec = float(entry["ask"] if direction > 0 else entry["bid"])
    exit_exec = float(exit_book["bid"] if direction > 0 else exit_book["ask"])
    quantity = float(notional_usd) / entry_exec
    gross_from_reference = quantity * direction * (exit_mid - reference_mid)
    signed_latency_usd = quantity * direction * (entry_mid - reference_mid)
    latency = max(0.0, signed_latency_usd)
    latency_benefit = max(0.0, -signed_latency_usd)
    # A favourable delayed mark is retained in gross rather than represented
    # as a negative cost.  An adverse delayed mark is an explicit latency cost.
    # In both cases gross - latency equals the actual delayed-entry mid PnL.
    gross_pnl = gross_from_reference + latency_benefit
    executable_before_fees = quantity * direction * (exit_exec - entry_exec)
    delayed_mid_pnl = quantity * direction * (exit_mid - entry_mid)
    spread_cost = delayed_mid_pnl - executable_before_fees
    if spread_cost < -1e-8:
        return None, "NEGATIVE_SPREAD_COST_INVARIANT"
    spread_cost = max(0.0, spread_cost)
    rate_bps = float(frais_taker_bps("HL") if fee_bps is None else fee_bps)
    fees = (abs(quantity * entry_exec) + abs(quantity * exit_exec)) * rate_bps / 10_000.0
    slippage = 0.0  # Full observed top capacity covers both marketable paper fills.
    net = gross_pnl - spread_cost - fees - slippage - latency
    expected = executable_before_fees - fees
    if not math.isclose(net, expected, abs_tol=1e-8):
        return None, "ECONOMIC_RECONCILIATION_FAILED"

    identity = {
        "metaorder_id": metaorder["metaorder_id"],
        "entry_ts_ms": entry["ts_ms"],
        "exit_ts_ms": exit_book["ts_ms"],
        "direction": direction,
        "horizon_ms": int(horizon_ms),
    }
    trade_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    signed_latency_move = direction * (entry_mid - reference_mid) / reference_mid * 10_000.0
    return {
        "trade_id": trade_id,
        "metaorder_id": metaorder["metaorder_id"],
        "vault": metaorder["vault"],
        "coin": metaorder["coin"],
        "direction": direction,
        "signal_ts_ms": signal_ms,
        "first_fill_ts_ms": int(metaorder.get("first_fill_ts_ms") or signal_ms),
        "signal_source": metaorder.get("signal_source") or "REST_BACKFILL",
        "causal_books_eligible": causal_books,
        "causal_forward_eligible": (
            metaorder.get("causal_forward_eligible") is True and causal_books
        ),
        "reference_ts_ms": reference["ts_ms"],
        "entry_ts_ms": entry["ts_ms"],
        "exit_ts_ms": exit_book["ts_ms"],
        "reference_lag_ms": reference_lag,
        "entry_target_lag_ms": entry_lag,
        "exit_target_lag_ms": exit_lag,
        "observed_latency_ms": int(entry["ts_ms"]) - signal_ms,
        "latency_move_signed_bps_diagnostic": round(signed_latency_move, 8),
        "latency_signed_usd": signed_latency_usd,
        "latency_benefit_in_gross_usd": latency_benefit,
        "latency_cost_method": "adverse_only;favourable_component_in_gross;exact_reconciliation",
        "entry_price": entry_exec,
        "exit_price": exit_exec,
        "quantity": quantity,
        "notional_usd": float(notional_usd),
        "entry_capacity_usd": float(entry["capacity_usd"]),
        "exit_capacity_usd": float(exit_book["capacity_usd"]),
        "gross_pnl_usd": gross_pnl,
        "fees_usd": fees,
        "spread_cost_usd": spread_cost,
        "slippage_cost_usd": slippage,
        "latency_cost_usd": latency,
        "net_pnl_usd": net,
        "liquidatable_net": True,
        "paper_read_only": True,
        "real_execution": False,
        "entry_source_line": entry["source_line"],
        "exit_source_line": exit_book["source_line"],
    }, "LIQUIDATABLE_NET"


def replay_metaorders(
    metaorders: Iterable[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    *,
    horizon_ms: int,
    start_ms: int | None = None,
    end_ms: int | None = None,
    direction_multiplier: int = 1,
    require_causal_observation: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counters: dict[str, int] = {
        "metaorders_considered": 0,
        "completed_positions": 0,
        "portfolio_capacity_rejected": 0,
    }
    active_exit_times: list[int] = []
    trades: list[dict[str, Any]] = []
    seen: set[str] = set()
    for metaorder in sorted(metaorders, key=lambda row: int(row["signal_ts_ms"])):
        signal_ms = int(metaorder["signal_ts_ms"])
        if start_ms is not None and signal_ms < int(start_ms):
            continue
        if end_ms is not None and signal_ms > int(end_ms):
            continue
        counters["metaorders_considered"] += 1
        if require_causal_observation and metaorder.get("causal_forward_eligible") is not True:
            counters["NON_CAUSAL_FORWARD_SIGNAL"] = counters.get(
                "NON_CAUSAL_FORWARD_SIGNAL", 0
            ) + 1
            continue
        trade, reason = execute_metaorder(
            metaorder,
            list(books_by_coin.get(str(metaorder["coin"]), [])),
            horizon_ms=int(horizon_ms),
            direction_multiplier=direction_multiplier,
            require_causal_books=require_causal_observation,
        )
        if trade is None:
            counters[reason] = counters.get(reason, 0) + 1
            continue
        active_exit_times = [ts for ts in active_exit_times if ts > int(trade["entry_ts_ms"])]
        if len(active_exit_times) >= MAX_OPEN_POSITIONS:
            counters["portfolio_capacity_rejected"] += 1
            continue
        if trade["trade_id"] in seen:
            counters["DUPLICATE_TRADE_ID_REJECTED"] = counters.get(
                "DUPLICATE_TRADE_ID_REJECTED", 0
            ) + 1
            continue
        seen.add(trade["trade_id"])
        active_exit_times.append(int(trade["exit_ts_ms"]))
        trades.append(trade)
        counters["completed_positions"] += 1
    return trades, counters


def summarize(trades: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(trades)
    ids = [str(row.get("trade_id") or "") for row in rows]
    duplicates = len(ids) - len(set(ids))
    gross = sum(float(row["gross_pnl_usd"]) for row in rows)
    fees = sum(float(row["fees_usd"]) for row in rows)
    spread = sum(float(row["spread_cost_usd"]) for row in rows)
    slippage = sum(float(row["slippage_cost_usd"]) for row in rows)
    latency = sum(float(row["latency_cost_usd"]) for row in rows)
    net = sum(float(row["net_pnl_usd"]) for row in rows)
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    wins = 0
    gains = 0.0
    losses = 0.0
    for row in sorted(rows, key=lambda item: int(item["exit_ts_ms"])):
        pnl = float(row["net_pnl_usd"])
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if pnl > 0:
            wins += 1
            gains += pnl
        elif pnl < 0:
            losses -= pnl
    return {
        "positions_ouvertes": len(rows),
        "positions_fermees": len(rows),
        "gross_pnl_usd": round(gross, 8),
        "fees_usd": round(fees, 8),
        "spread_cost_usd": round(spread, 8),
        "slippage_cost_usd": round(slippage, 8),
        "latency_cost_usd": round(latency, 8),
        "net_pnl_usd": round(net, 8),
        "roi_pct": round(net / 1000.0 * 100.0, 8),
        "max_drawdown_usd": round(max_drawdown, 8),
        "hit_rate": round(wins / len(rows), 8) if rows else 0.0,
        # JSON has no portable Infinity value.  An all-win sample has an
        # undefined PF, not an infinite economic proof.
        "profit_factor": round(gains / losses, 8) if losses > 0 else None,
        "LIQUIDATABLE_NET": bool(rows) and all(row.get("liquidatable_net") is True for row in rows),
        "duplicate_trade_ids": duplicates,
        "trade_ids_count": len(set(ids)),
        "trade_ids_sha256": hashlib.sha256("\n".join(sorted(set(ids))).encode("utf-8")).hexdigest(),
        "economic_reconciliation_ok": math.isclose(
            gross - fees - spread - slippage - latency, net, abs_tol=1e-6
        ),
    }


def temporal_bounds(metaorders: list[Mapping[str, Any]]) -> dict[str, int | None]:
    timestamps = sorted(int(row["signal_ts_ms"]) for row in metaorders)
    if len(timestamps) < 3:
        return {key: None for key in (
            "train_start_ms", "train_end_ms", "validation_start_ms", "validation_end_ms",
            "oos_start_ms", "oos_end_ms", "purge_ms",
        )}
    train_index = min(len(timestamps) - 2, max(0, int(len(timestamps) * TRAIN_FRACTION) - 1))
    validation_index = min(
        len(timestamps) - 1,
        max(train_index + 1, int(len(timestamps) * (TRAIN_FRACTION + VALIDATION_FRACTION)) - 1),
    )
    purge = max(HORIZONS_MS)
    train_cut = timestamps[train_index]
    oos_cut = timestamps[validation_index]
    return {
        "train_start_ms": timestamps[0],
        "train_end_ms": train_cut - purge,
        "validation_start_ms": train_cut,
        "validation_end_ms": oos_cut - purge,
        "oos_start_ms": oos_cut,
        "oos_end_ms": timestamps[-1],
        "purge_ms": purge,
        "validation_empty_after_purge": oos_cut - purge < train_cut,
    }


def calibrate_train_only(
    metaorders: list[Mapping[str, Any]], books_by_coin: Mapping[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    bounds = temporal_bounds(metaorders)
    grid: list[dict[str, Any]] = []
    for horizon in HORIZONS_MS:
        trades, diagnostics = replay_metaorders(
            metaorders,
            books_by_coin,
            horizon_ms=horizon,
            start_ms=bounds.get("train_start_ms"),
            end_ms=bounds.get("train_end_ms"),
        )
        summary = summarize(trades)
        grid.append({"horizon_ms": horizon, "summary": summary, "diagnostics": diagnostics,
                     "eligible": summary["positions_fermees"] >= MIN_TRAIN_TRADES})
    eligible = [row for row in grid if row["eligible"]]
    selected = max(
        eligible,
        key=lambda row: (float(row["summary"]["net_pnl_usd"]), -int(row["horizon_ms"])),
        default=None,
    )
    return {
        "status": "TRAIN_SELECTED" if selected else "KILL_TRAIN_INSUFFICIENT_EXECUTABLE_EPISODES",
        "selection_eligible": selected is not None,
        "selected_horizon_ms": int(selected["horizon_ms"]) if selected else int(HORIZONS_MS[0]),
        "bounds": bounds,
        "grid": grid,
        "selection_scope": "TRAIN_ONLY",
    }


def evaluate_frozen(
    metaorders: list[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    *,
    frozen_parameters: Mapping[str, Any],
    frozen_at_ms: int,
) -> dict[str, Any]:
    bounds = dict(frozen_parameters.get("walk_forward_bounds") or {})
    horizon = int(frozen_parameters.get("selected_horizon_ms") or HORIZONS_MS[0])
    segments = {
        "train": (bounds.get("train_start_ms"), bounds.get("train_end_ms")),
        "validation": (bounds.get("validation_start_ms"), bounds.get("validation_end_ms")),
        "oos": (bounds.get("oos_start_ms"), bounds.get("oos_end_ms")),
        "forward": (max(int(frozen_at_ms) + 1, int(bounds.get("oos_end_ms") or 0) + 1), None),
    }
    result: dict[str, Any] = {"horizon_ms": horizon, "bounds": bounds, "segments": {}, "trades": {}}
    all_trades: list[dict[str, Any]] = []
    for name, (start_ms, end_ms) in segments.items():
        trades, diagnostics = replay_metaorders(
            metaorders,
            books_by_coin,
            horizon_ms=horizon,
            start_ms=start_ms,
            end_ms=end_ms,
            require_causal_observation=name == "forward",
        )
        result["segments"][name] = {"summary": summarize(trades), "diagnostics": diagnostics}
        result["trades"][name] = trades
        all_trades.extend(trades)
    result["combined_summary"] = summarize(all_trades)
    inverted, inverted_diag = replay_metaorders(
        metaorders,
        books_by_coin,
        horizon_ms=horizon,
        start_ms=bounds.get("oos_start_ms"),
        end_ms=bounds.get("oos_end_ms"),
        direction_multiplier=-1,
    )
    result["placebo_inverted_oos"] = {
        "summary": summarize(inverted),
        "diagnostics": inverted_diag,
    }
    return result


def temporal_evidence(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    segments = evaluation.get("segments") if isinstance(evaluation.get("segments"), Mapping) else {}
    oos_summary = (segments.get("oos") or {}).get("summary") or {}
    forward_summary = (segments.get("forward") or {}).get("summary") or {}
    placebo_summary = (evaluation.get("placebo_inverted_oos") or {}).get("summary") or {}
    oos_count = int(oos_summary.get("positions_fermees") or 0)
    forward_count = int(forward_summary.get("positions_fermees") or 0)
    placebo_count = int(placebo_summary.get("positions_fermees") or 0)
    oos_net = oos_summary.get("net_pnl_usd") if oos_count > 0 else None
    forward_net = forward_summary.get("net_pnl_usd") if forward_count > 0 else None
    placebo_net = placebo_summary.get("net_pnl_usd") if placebo_count > 0 else None
    forward_trades = (
        (evaluation.get("trades") or {}).get("forward") or []
        if isinstance(evaluation.get("trades"), Mapping)
        else []
    )
    causal_forward = bool(forward_trades) and all(
        row.get("causal_forward_eligible") is True for row in forward_trades
    )
    return {
        "oos": {
            "net_pnl_usd": oos_net,
            "sample_count": oos_count,
            "no_lookahead": True,
            "purged": True,
        },
        "forward": {
            "net_pnl_usd": forward_net,
            "sample_count": forward_count,
            "post_freeze": causal_forward,
            "causal_live_only": causal_forward,
        },
        "placebos": {
            "beaten": (
                oos_net is not None
                and placebo_net is not None
                and float(oos_net) > float(placebo_net)
            ),
            "candidate_net_usd": oos_net,
            "placebo_net_usd": placebo_net,
            "method": "same_metaorders_inverted_direction",
        },
    }


__all__ = [
    "COPY_DELAY_MS", "HORIZONS_MS", "MAX_OPEN_POSITIONS", "METAORDER_GAP_MS",
    "NOTIONAL_USD", "SCHEMA_VERSION", "calibrate_train_only", "cluster_metaorders",
    "evaluate_frozen", "execute_metaorder", "load_observed_books", "protocol_signature",
    "replay_metaorders", "summarize", "temporal_bounds", "temporal_evidence",
]
