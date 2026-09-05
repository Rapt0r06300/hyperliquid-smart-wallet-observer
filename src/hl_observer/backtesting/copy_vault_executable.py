"""Replay Copy-Vault causal et exécutable en PAPER sur carnets observés."""
from __future__ import annotations

import bisect
import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

from hl_observer.backtesting.copy_vault_book_loader import load_observed_books
from hl_observer.backtesting.copy_vault_causal_selection import (
    cluster_metaorders,
    select_causal_protocol_inputs,
    select_observed_continuations,
)
from hl_observer.backtesting.copy_vault_protocol import (
    CHECKPOINT_COLLECTOR_PROTOCOL,
    COPY_DELAY_MS,
    HORIZONS_MS,
    MAX_OPEN_POSITIONS,
    MAX_REFERENCE_LAG_MS,
    MAX_TARGET_LAG_MS,
    METAORDER_GAP_MS,
    MIN_TRAIN_TRADES,
    NOTIONAL_USD,
    PROTOCOL_NAME,
    TRAIN_ECONOMIC_GATE_VERSION,
    TRAIN_FRACTION,
    VALIDATION_FRACTION,
    canonical_metaorder_id,
    classify_live_entry_action,
    expected_open_direction,
    protocol_signature,
)
from hl_observer.economics.assumptions import (
    CostComponentReceipt,
    EconomicConfigError,
    EconomicRunMode,
    ZeroCostReason,
    is_certifiable_mode,
)
from hl_observer.economics.families import build_copy_vault_contract

SCHEMA_VERSION = "hypersmart.copy_vault_executable.v1"



def _first_at_or_after(
    rows: list[dict[str, Any]], target_ms: int, max_lag_ms: int
) -> tuple[dict[str, Any] | None, int | None]:
    timestamps = [int(row["ts_ms"]) for row in rows]
    index = bisect.bisect_left(timestamps, int(target_ms))
    if index >= len(rows):
        return None, None
    lag = int(rows[index]["ts_ms"]) - int(target_ms)
    return (rows[index], lag) if 0 <= lag <= int(max_lag_ms) else (None, lag)


def _exact_checkpoint_triplet(
    metaorder: Mapping[str, Any],
    books: list[dict[str, Any]],
    *,
    horizon_ms: int,
    copy_delay_ms: int,
    max_reference_lag_ms: int,
    max_target_lag_ms: int,
) -> tuple[
    tuple[dict[str, Any], dict[str, Any], dict[str, Any], int, int, int] | None,
    str | None,
]:
    """Select only checkpoints cryptographically bound to this metaorder."""
    metaorder_id = str(metaorder.get("metaorder_id") or "")
    matching = [
        row for row in books
        if str(row.get("metaorder_id") or "") == metaorder_id
        and str(row.get("collector_protocol") or "") == CHECKPOINT_COLLECTOR_PROTOCOL
        and row.get("checkpoint_id")
    ]
    if not matching:
        return None, None
    expected_stages = ("REFERENCE", "ENTRY", f"EXIT_{int(horizon_ms)}")
    expected_checkpoint_ids = (
        f"{metaorder_id}:REFERENCE",
        f"{metaorder_id}:ENTRY",
        f"{metaorder_id}:EXIT:{int(horizon_ms)}",
    )
    selected: list[dict[str, Any]] = []
    for stage, checkpoint_id in zip(expected_stages, expected_checkpoint_ids, strict=True):
        candidates = [row for row in matching if row.get("checkpoint_stage") == stage]
        if len(candidates) != 1:
            return None, (
                "AMBIGUOUS_EXACT_METAORDER_CHECKPOINT"
                if len(candidates) > 1
                else "MISSING_EXACT_METAORDER_CHECKPOINT"
            )
        if str(candidates[0].get("checkpoint_id") or "") != checkpoint_id:
            return None, "CHECKPOINT_ID_BINDING_MISMATCH"
        selected.append(candidates[0])
    reference, entry, exit_book = selected
    signal_ms = int(metaorder["signal_ts_ms"])
    expected_targets = (
        signal_ms,
        signal_ms + int(copy_delay_ms),
        int(entry["ts_ms"]) + int(horizon_ms),
    )
    lags: list[int] = []
    for index, (row, expected_target) in enumerate(zip(selected, expected_targets, strict=True)):
        target = int(row.get("checkpoint_target_ms") or 0)
        if target != expected_target:
            return None, "CHECKPOINT_TARGET_BINDING_MISMATCH"
        lag = int(row["ts_ms"]) - target
        allowed = max_reference_lag_ms if index == 0 else max_target_lag_ms
        if lag < 0 or lag > int(allowed):
            return None, "STALE_EXACT_METAORDER_CHECKPOINT"
        lags.append(lag)
    return (reference, entry, exit_book, lags[0], lags[1], lags[2]), None


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
    economic_mode: EconomicRunMode | str = EconomicRunMode.EXPLORATORY,
) -> tuple[dict[str, Any] | None, str]:
    """Execute one closed paper episode or return an explicit refusal code."""
    contract = build_copy_vault_contract(
        mode=economic_mode,
        notional_usd=float(notional_usd),
        copy_delay_ms=float(copy_delay_ms),
        max_reference_lag_ms=float(max_reference_lag_ms),
        max_target_lag_ms=float(max_target_lag_ms),
    )
    if fee_bps is not None and is_certifiable_mode(economic_mode):
        raise EconomicConfigError(
            "fee_bps local interdit en mode certifiable; utiliser l'autorite de frais canonique",
            field="fee_bps",
        )
    canonical_fee_bps = float(
        contract.registry.get("fee.taker.hyperliquid.bps").value
    )
    rate_bps = canonical_fee_bps if fee_bps is None else float(fee_bps)
    if not math.isfinite(rate_bps) or rate_bps < 0.0:
        raise EconomicConfigError("fee_bps invalide", field="fee_bps")
    if not books:
        return None, "NO_OBSERVED_BOOK_FOR_COIN"
    signal_ms = int(metaorder["signal_ts_ms"])
    checkpoint_triplet, checkpoint_reason = _exact_checkpoint_triplet(
        metaorder,
        books,
        horizon_ms=int(horizon_ms),
        copy_delay_ms=int(copy_delay_ms),
        max_reference_lag_ms=int(max_reference_lag_ms),
        max_target_lag_ms=int(max_target_lag_ms),
    )
    if checkpoint_reason is not None:
        return None, checkpoint_reason
    if checkpoint_triplet is not None:
        reference, entry, exit_book, reference_lag, entry_lag, exit_lag = checkpoint_triplet
        book_binding_method = "EXACT_METAORDER_CHECKPOINTS"
    else:
        continuous_books = [row for row in books if not row.get("checkpoint_id")]
        if not continuous_books:
            return None, "MISSING_EXACT_METAORDER_CHECKPOINT"
        reference, reference_lag = _first_at_or_after(
            continuous_books, signal_ms, max_reference_lag_ms
        )
        if reference is None:
            return None, "STALE_OR_MISSING_REFERENCE_BOOK"
        entry_target_ms = signal_ms + int(copy_delay_ms)
        entry, entry_lag = _first_at_or_after(
            continuous_books, entry_target_ms, max_target_lag_ms
        )
        if entry is None:
            return None, "STALE_OR_MISSING_ENTRY_BOOK"
        exit_target_ms = int(entry["ts_ms"]) + int(horizon_ms)
        exit_book, exit_lag = _first_at_or_after(
            continuous_books, exit_target_ms, max_target_lag_ms
        )
        if exit_book is None:
            return None, "STALE_OR_MISSING_EXIT_BOOK"
        book_binding_method = "CONTINUOUS_CAUSAL_BOOK"
    causal_books = all(row.get("causal_observation") is True for row in (reference, entry, exit_book))
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
    gross_pnl = gross_from_reference + latency_benefit
    executable_before_fees = quantity * direction * (exit_exec - entry_exec)
    delayed_mid_pnl = quantity * direction * (exit_mid - entry_mid)
    spread_cost = delayed_mid_pnl - executable_before_fees
    if spread_cost < -1e-8:
        return None, "NEGATIVE_SPREAD_COST_INVARIANT"
    spread_cost = max(0.0, spread_cost)
    fees = (abs(quantity * entry_exec) + abs(quantity * exit_exec)) * rate_bps / 10_000.0
    slippage = 0.0
    net = gross_pnl - spread_cost - fees - slippage - latency
    expected = executable_before_fees - fees
    if not math.isclose(net, expected, abs_tol=1e-8):
        return None, "ECONOMIC_RECONCILIATION_FAILED"
    identity = {
        "metaorder_id": metaorder["metaorder_id"], "entry_ts_ms": entry["ts_ms"],
        "exit_ts_ms": exit_book["ts_ms"], "direction": direction, "horizon_ms": int(horizon_ms),
    }
    trade_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    signed_latency_move = direction * (entry_mid - reference_mid) / reference_mid * 10_000.0
    latency_zero_reason = (
        ZeroCostReason.NOT_APPLICABLE
        if latency == 0.0 and signed_latency_usd < 0.0
        else ZeroCostReason.MEASURED_ZERO
        if latency == 0.0
        else None
    )
    cost_component_receipts = {
        "fees": CostComponentReceipt(
            component="fees",
            amount_usd=fees,
            zero_reason=ZeroCostReason.MEASURED_ZERO if fees == 0.0 else None,
            formula_id="copy_vault.round_trip_fee.v1",
            reality_model_version=contract.reality_model_version,
            provenance_ids=("fee.taker.hyperliquid.bps", "copy_vault.paper_notional_usd"),
        ).as_dict(),
        "spread": CostComponentReceipt(
            component="spread",
            amount_usd=spread_cost,
            zero_reason=ZeroCostReason.MEASURED_ZERO if spread_cost == 0.0 else None,
            formula_id="copy_vault.executable_bid_ask_spread.v1",
            reality_model_version=contract.reality_model_version,
            provenance_ids=("entry_book.bid_ask", "exit_book.bid_ask"),
        ).as_dict(),
        "slippage": CostComponentReceipt(
            component="slippage",
            amount_usd=slippage,
            zero_reason=ZeroCostReason.NOT_APPLICABLE,
            formula_id="copy_vault.full_top_capacity.v1",
            reality_model_version=contract.reality_model_version,
            provenance_ids=("entry_capacity_usd", "exit_capacity_usd"),
        ).as_dict(),
        "latency": CostComponentReceipt(
            component="latency",
            amount_usd=latency,
            zero_reason=latency_zero_reason,
            formula_id="copy_vault.adverse_latency.v1",
            reality_model_version=contract.reality_model_version,
            provenance_ids=("reference_ts_ms", "entry_ts_ms"),
        ).as_dict(),
    }
    economic_receipt = contract.receipt()
    if fee_bps is not None:
        economic_receipt["certification"] = {
            **dict(economic_receipt["certification"]),
            "ready": False,
            "assumption_snapshot_hash": None,
            "failures": [
                *list(economic_receipt["certification"].get("failures") or ()),
                {
                    "assumption_id": "fee.taker.hyperliquid.bps",
                    "reason": "EXPLORATORY_LOCAL_FEE_OVERRIDE",
                },
            ],
        }
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
        "causal_forward_eligible": metaorder.get("causal_forward_eligible") is True and causal_books,
        "book_binding_method": book_binding_method,
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
        "cost_component_receipts": cost_component_receipts,
        "slippage_zero_reason": ZeroCostReason.NOT_APPLICABLE.value,
        "latency_zero_reason": (
            latency_zero_reason.value if latency_zero_reason is not None else None
        ),
        "assumption_snapshot_hash": contract.registry.snapshot_hash(),
        "economic_contract": economic_receipt,
        "fee_provenance_source": (
            "CANONICAL_ECONOMIC_ASSUMPTION_REGISTRY"
            if fee_bps is None
            else "EXPLORATORY_EXPLICIT_NON_CERTIFIABLE_OVERRIDE"
        ),
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
    *, horizon_ms: int, start_ms: int | None = None, end_ms: int | None = None,
    direction_multiplier: int = 1, require_causal_observation: bool = False,
    economic_mode: EconomicRunMode | str = EconomicRunMode.EXPLORATORY,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counters: dict[str, int] = {
        "metaorders_considered": 0, "completed_positions": 0, "portfolio_capacity_rejected": 0,
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
            counters["NON_CAUSAL_FORWARD_SIGNAL"] = counters.get("NON_CAUSAL_FORWARD_SIGNAL", 0) + 1
            continue
        trade, reason = execute_metaorder(
            metaorder, list(books_by_coin.get(str(metaorder["coin"]), [])),
            horizon_ms=int(horizon_ms), direction_multiplier=direction_multiplier,
            require_causal_books=require_causal_observation,
            economic_mode=economic_mode,
        )
        if trade is None:
            counters[reason] = counters.get(reason, 0) + 1
            continue
        active_exit_times = [ts for ts in active_exit_times if ts > int(trade["entry_ts_ms"])]
        if len(active_exit_times) >= MAX_OPEN_POSITIONS:
            counters["portfolio_capacity_rejected"] += 1
            continue
        if trade["trade_id"] in seen:
            counters["DUPLICATE_TRADE_ID_REJECTED"] = counters.get("DUPLICATE_TRADE_ID_REJECTED", 0) + 1
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
    equity = peak = max_drawdown = gains = losses = 0.0
    wins = 0
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
        "positions_ouvertes": len(rows), "positions_fermees": len(rows),
        "gross_pnl_usd": round(gross, 8), "fees_usd": round(fees, 8),
        "spread_cost_usd": round(spread, 8), "slippage_cost_usd": round(slippage, 8),
        "latency_cost_usd": round(latency, 8), "net_pnl_usd": round(net, 8),
        "roi_pct": round(net / 1000.0 * 100.0, 8),
        "max_drawdown_usd": round(max_drawdown, 8),
        "hit_rate": round(wins / len(rows), 8) if rows else 0.0,
        "profit_factor": round(gains / losses, 8) if losses > 0 else None,
        "LIQUIDATABLE_NET": bool(rows) and all(row.get("liquidatable_net") is True for row in rows),
        "duplicate_trade_ids": duplicates, "trade_ids_count": len(set(ids)),
        "trade_ids_sha256": hashlib.sha256("\n".join(sorted(set(ids))).encode("utf-8")).hexdigest(),
        "economic_reconciliation_ok": math.isclose(
            gross - fees - spread - slippage - latency, net, abs_tol=1e-6
        ),
    }


def temporal_bounds(
    metaorders: list[Mapping[str, Any]], *, purge_ms: int | None = None,
) -> dict[str, int | bool | None]:
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
    purge = max(HORIZONS_MS) if purge_ms is None else max(0, int(purge_ms))
    train_cut = timestamps[train_index]
    oos_cut = timestamps[validation_index]
    return {
        "train_start_ms": timestamps[0], "train_end_ms": train_cut - purge,
        "validation_start_ms": train_cut, "validation_end_ms": oos_cut - purge,
        "oos_start_ms": oos_cut, "oos_end_ms": timestamps[-1], "purge_ms": purge,
        "validation_empty_after_purge": oos_cut - purge < train_cut,
    }


def calibrate_train_only(
    metaorders: list[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    *, require_causal_observation: bool = False,
) -> dict[str, Any]:
    grid: list[dict[str, Any]] = []
    for horizon in HORIZONS_MS:
        purge_ms = COPY_DELAY_MS + int(horizon) + MAX_TARGET_LAG_MS
        bounds = temporal_bounds(metaorders, purge_ms=purge_ms)
        trades, diagnostics = replay_metaorders(
            metaorders, books_by_coin, horizon_ms=horizon,
            start_ms=bounds.get("train_start_ms"), end_ms=bounds.get("train_end_ms"),
            require_causal_observation=require_causal_observation,
        )
        summary = summarize(trades)
        profit_factor = summary.get("profit_factor")
        all_wins_without_loss_denominator = bool(
            summary["positions_fermees"] >= MIN_TRAIN_TRADES
            and float(summary.get("net_pnl_usd") or 0.0) > 0.0
            and float(summary.get("hit_rate") or 0.0) == 1.0 and profit_factor is None
        )
        economic_gate = bool(
            summary["positions_fermees"] >= MIN_TRAIN_TRADES
            and summary.get("LIQUIDATABLE_NET") is True
            and summary.get("economic_reconciliation_ok") is True
            and float(summary.get("net_pnl_usd") or 0.0) > 0.0
            and (all_wins_without_loss_denominator or (
                profit_factor is not None and float(profit_factor) > 1.0
            ))
        )
        grid.append({
            "horizon_ms": horizon, "bounds": bounds, "summary": summary,
            "diagnostics": diagnostics,
            "sample_eligible": summary["positions_fermees"] >= MIN_TRAIN_TRADES,
            "economic_gate": {
                "net_positive": float(summary.get("net_pnl_usd") or 0.0) > 0.0,
                "profit_factor_above_one": bool(
                    profit_factor is not None and float(profit_factor) > 1.0
                ),
                "all_wins_without_loss_denominator": all_wins_without_loss_denominator,
                "liquidatable_net": summary.get("LIQUIDATABLE_NET") is True,
                "economic_reconciliation_ok": summary.get("economic_reconciliation_ok") is True,
            },
            "eligible": economic_gate,
        })
    eligible = [row for row in grid if row["eligible"]]
    selected = max(
        eligible,
        key=lambda row: (float(row["summary"]["net_pnl_usd"]), -int(row["horizon_ms"])),
        default=None,
    )
    selected_horizon = int(selected["horizon_ms"]) if selected else int(HORIZONS_MS[0])
    selected_bounds = dict(selected["bounds"]) if selected else dict(grid[0]["bounds"])
    has_sufficient_sample = any(row["sample_eligible"] for row in grid)
    return {
        "status": (
            "TRAIN_SELECTED" if selected else
            "KILL_TRAIN_NO_POSITIVE_RECONCILED_CANDIDATE" if has_sufficient_sample else
            "KILL_TRAIN_INSUFFICIENT_EXECUTABLE_EPISODES"
        ),
        "selection_eligible": selected is not None,
        "train_economic_gate": TRAIN_ECONOMIC_GATE_VERSION,
        "minimum_train_trades": MIN_TRAIN_TRADES,
        "selected_horizon_ms": selected_horizon,
        "bounds": selected_bounds, "grid": grid, "selection_scope": "TRAIN_ONLY",
        "causal_observation_required": bool(require_causal_observation),
    }


def evaluate_frozen(
    metaorders: list[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    *,
    frozen_parameters: Mapping[str, Any],
    frozen_at_ms: int,
    economic_mode: EconomicRunMode | str = EconomicRunMode.EXPLORATORY,
) -> dict[str, Any]:
    contract = build_copy_vault_contract(
        mode=economic_mode,
        notional_usd=float(NOTIONAL_USD),
        copy_delay_ms=float(COPY_DELAY_MS),
        max_reference_lag_ms=float(MAX_REFERENCE_LAG_MS),
        max_target_lag_ms=float(MAX_TARGET_LAG_MS),
    )
    bounds = dict(frozen_parameters.get("walk_forward_bounds") or {})
    horizon = int(frozen_parameters.get("selected_horizon_ms") or HORIZONS_MS[0])
    causal_all_segments = frozen_parameters.get("causal_observation_required_all_segments") is True
    segments = {
        "train": (bounds.get("train_start_ms"), bounds.get("train_end_ms")),
        "validation": (bounds.get("validation_start_ms"), bounds.get("validation_end_ms")),
        "oos": (bounds.get("oos_start_ms"), bounds.get("oos_end_ms")),
        "forward": (max(int(frozen_at_ms) + 1, int(bounds.get("oos_end_ms") or 0) + 1), None),
    }
    result: dict[str, Any] = {
        "horizon_ms": horizon,
        "bounds": bounds,
        "segments": {},
        "trades": {},
        "economic_contract": contract.receipt(),
        "assumption_snapshot_hash": contract.registry.snapshot_hash(),
    }
    all_trades: list[dict[str, Any]] = []
    for name, (start_ms, end_ms) in segments.items():
        trades, diagnostics = replay_metaorders(
            metaorders, books_by_coin, horizon_ms=horizon, start_ms=start_ms, end_ms=end_ms,
            require_causal_observation=causal_all_segments or name == "forward",
            economic_mode=economic_mode,
        )
        result["segments"][name] = {"summary": summarize(trades), "diagnostics": diagnostics}
        result["trades"][name] = trades
        all_trades.extend(trades)
    result["combined_summary"] = summarize(all_trades)
    inverted, inverted_diag = replay_metaorders(
        metaorders, books_by_coin, horizon_ms=horizon,
        start_ms=bounds.get("oos_start_ms"), end_ms=bounds.get("oos_end_ms"),
        direction_multiplier=-1, require_causal_observation=causal_all_segments,
        economic_mode=economic_mode,
    )
    result["placebo_inverted_oos"] = {
        "summary": summarize(inverted), "diagnostics": inverted_diag,
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
    placebo_net = placebo_summary.get("net_pnl_usd") if placebo_count > 0 else None
    forward_trades = (
        (evaluation.get("trades") or {}).get("forward") or []
        if isinstance(evaluation.get("trades"), Mapping) else []
    )
    causal_forward = bool(forward_trades) and all(
        row.get("causal_forward_eligible") is True for row in forward_trades
    )

    def proof_segment(summary: Mapping[str, Any], *, count: int) -> dict[str, Any]:
        return {key: summary.get(key) for key in (
            "gross_pnl_usd", "fees_usd", "spread_cost_usd", "slippage_cost_usd",
            "latency_cost_usd", "net_pnl_usd", "trade_ids_count", "trade_ids_sha256",
            "duplicate_trade_ids",
        )} | {"sample_count": count, "liquidatable_net": summary.get("LIQUIDATABLE_NET") is True}

    return {
        "oos": {**proof_segment(oos_summary, count=oos_count), "no_lookahead": True, "purged": True},
        "forward": {
            **proof_segment(forward_summary, count=forward_count),
            "post_freeze": causal_forward, "causal_live_only": causal_forward,
        },
        "placebos": {
            "beaten": oos_net is not None and placebo_net is not None and float(oos_net) > float(placebo_net),
            "candidate_net_usd": oos_net, "placebo_net_usd": placebo_net,
            "method": "same_metaorders_inverted_direction",
        },
    }


__all__ = [
    "CHECKPOINT_COLLECTOR_PROTOCOL", "COPY_DELAY_MS", "HORIZONS_MS", "MAX_OPEN_POSITIONS",
    "MAX_TARGET_LAG_MS", "METAORDER_GAP_MS", "NOTIONAL_USD", "SCHEMA_VERSION",
    "calibrate_train_only", "canonical_metaorder_id", "classify_live_entry_action",
    "cluster_metaorders", "evaluate_frozen", "execute_metaorder", "expected_open_direction",
    "load_observed_books", "PROTOCOL_NAME", "protocol_signature", "replay_metaorders", "select_causal_protocol_inputs",
    "select_observed_continuations", "summarize", "temporal_bounds", "temporal_evidence",
]
