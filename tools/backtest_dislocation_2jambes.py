"""Causal two-leg paper replay for Hyperliquid/Binance dislocations.

The module is intentionally read-only.  It consumes locally recorded BBO
events, waits for the configured execution latency, crosses the executable
bid/ask on both venues at entry and exit, and reports every cost component it
can actually measure.  Depth/slippage cannot be inferred from BBO alone, so a
BBO-only result is never labelled ``LIQUIDATABLE_NET``.
"""
from __future__ import annotations

import argparse
import bisect
import glob
import gzip
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting.cross_venue_certified import (  # noqa: E402
    FOUR_FILL_CONTRACT_VERSION,
)
from hl_observer.backtesting.cross_venue_certified import (  # noqa: E402
    SOURCE_MODE as CERTIFIED_CROSS_SOURCE_MODE,
)
from hl_observer.economics.assumptions import (  # noqa: E402
    CostComponentReceipt,
    EconomicRunMode,
    ZeroCostReason,
)
from hl_observer.economics.families import (  # noqa: E402
    FamilyEconomicContract,
    build_cross_venue_contract,
)


def economic_contract(
    mode: EconomicRunMode | str = EconomicRunMode.EXPLORATORY,
) -> FamilyEconomicContract:
    return build_cross_venue_contract(mode=mode)


_DEFAULT_ECONOMIC_CONTRACT = economic_contract()
_CROSS_REALITY_MODEL_VERSION = _DEFAULT_ECONOMIC_CONTRACT.reality_model_version

SEUIL_ENTREE_BPS = 15.0
SEUIL_SORTIE_BPS = 3.0
STOP_AGGRAVATION_BPS = 25.0
HORIZON_MAX_S = 4 * 3600.0
FRAICHEUR_MAX_MS = float(
    _DEFAULT_ECONOMIC_CONTRACT.registry.get("cross_venue.max_book_age_ms").value
)
LATENCE_MS = float(
    _DEFAULT_ECONOMIC_CONTRACT.registry.get("cross_venue.entry_latency_ms").value
)
FEES_AR_BPS = float(
    _DEFAULT_ECONOMIC_CONTRACT.registry.get("cross_venue.round_trip_fee_bps").value
)
ECART_MAX_ENTREE_BPS = 100.0
NOTIONAL_USD = float(
    _DEFAULT_ECONOMIC_CONTRACT.registry.get("cross_venue.paper_notional_usd").value
)
DEPTH_FRESHNESS_MS = 3000.0
MIN_EXECUTABLE_EDGE_BPS = float(
    _DEFAULT_ECONOMIC_CONTRACT.registry.get("cross_venue.minimum_entry_edge_bps").value
)
MAX_OBSERVATION_GAP_MS = 300_000.0

CROSS_WALK_FORWARD_PROTOCOL = "cross_certified_atomic_bbo_walk_forward_v4"
CROSS_TRAIN_FRACTION = 0.60
CROSS_VALIDATION_FRACTION = 0.20
CROSS_PURGE_MS = HORIZON_MAX_S * 1000.0
CROSS_MIN_TRAIN_TRADES = 8
CROSS_WALK_FORWARD_GRID = tuple(
    {
        "seuil_entree": entry,
        "stop_bps": stop,
        "horizon_s": horizon,
        "min_executable_edge_bps": edge,
    }
    for entry in (15.0, 30.0)
    for stop in (15.0, 25.0)
    for horizon in (900.0, 3600.0, 14400.0)
    for edge in (MIN_EXECUTABLE_EDGE_BPS,)
)

COINS_COMMUNS = ("BTC", "ETH", "SOL", "AVAX", "INJ", "DASH", "NEO", "LINK", "AAVE", "ONDO")


def _basis_bps(hl, bn):
    """Return ``mid_HL - mid_BIN`` in basis points."""
    mh = 0.5 * (hl[1] + hl[2])
    mb = 0.5 * (bn[1] + bn[2])
    if mh <= 0 or mb <= 0:
        return None
    return (mh - mb) / (0.5 * (mh + mb)) * 1e4


def _net_trade_bps(hl_in, bn_in, hl_out, bn_out, *, sens: int, fees_ar_bps: float) -> float:
    """Executable two-leg/four-fill return, including configured fees."""
    hb_i, ha_i = hl_in[1], hl_in[2]
    bb_i, ba_i = bn_in[1], bn_in[2]
    hb_o, ha_o = hl_out[1], hl_out[2]
    bb_o, ba_o = bn_out[1], bn_out[2]
    if sens > 0:
        pnl_hl = (hb_i - ha_o) / hb_i
        pnl_bin = (bb_o - ba_i) / ba_i
    else:
        pnl_hl = (hb_o - ha_i) / ha_i
        pnl_bin = (bb_i - ba_o) / bb_i
    return (pnl_hl + pnl_bin) * 1e4 - fees_ar_bps


def _mid_trade_bps(hl_in, bn_in, hl_out, bn_out, *, sens: int) -> float:
    """Gross two-leg return at mids, used only for cost reconciliation."""
    hm_i = 0.5 * (hl_in[1] + hl_in[2])
    bm_i = 0.5 * (bn_in[1] + bn_in[2])
    hm_o = 0.5 * (hl_out[1] + hl_out[2])
    bm_o = 0.5 * (bn_out[1] + bn_out[2])
    if sens > 0:
        return ((hm_i - hm_o) / hm_i + (bm_o - bm_i) / bm_i) * 1e4
    return ((hm_o - hm_i) / hm_i + (bm_i - bm_o) / bm_i) * 1e4


def _convergence_edge_bps(hl, bn, *, sens: int, fees_ar_bps: float) -> float:
    """Causal net edge if both mids converge while observed spreads persist.

    The estimate uses only the current four executable BBO sides.  It is a
    validity gate, not a fitted strategy threshold: an entry whose complete
    two-leg round trip cannot cover its observed spreads and configured fees
    is economically impossible even under immediate midpoint convergence.
    """

    hl_mid = 0.5 * (hl[1] + hl[2])
    bin_mid = 0.5 * (bn[1] + bn[2])
    fair = 0.5 * (hl_mid + bin_mid)
    hl_half_spread = 0.5 * (hl[2] - hl[1])
    bin_half_spread = 0.5 * (bn[2] - bn[1])
    synthetic_hl = (hl[0], fair - hl_half_spread, fair + hl_half_spread)
    synthetic_bin = (bn[0], fair - bin_half_spread, fair + bin_half_spread)
    return _net_trade_bps(
        hl,
        bn,
        synthetic_hl,
        synthetic_bin,
        sens=sens,
        fees_ar_bps=float(fees_ar_bps),
    )


def _trade_id(*, coin: str, ts_detect: float, ts_in: float, ts_out: float, sens: int) -> str:
    identity = f"{coin}|{ts_detect:.3f}|{ts_in:.3f}|{ts_out:.3f}|{sens}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _depth_at(
    depth_rows: list[tuple[float, float]],
    timestamp_ms: float,
    *,
    freshness_ms: float,
) -> dict | None:
    """Return the latest causal top-book capacity at or before ``timestamp_ms``."""

    if not depth_rows:
        return None
    index = bisect.bisect_right(depth_rows, (float(timestamp_ms), float("inf"))) - 1
    if index < 0:
        return None
    observed_ms, capacity_usd = depth_rows[index]
    age_ms = float(timestamp_ms) - observed_ms
    if age_ms < 0 or age_ms > float(freshness_ms) or capacity_usd <= 0:
        return None
    return {
        "observed_ms": observed_ms,
        "age_ms": age_ms,
        "capacity_usd": capacity_usd,
    }


def backtester(
    series: dict,
    *,
    seuil_entree=SEUIL_ENTREE_BPS,
    seuil_sortie=SEUIL_SORTIE_BPS,
    stop_bps=STOP_AGGRAVATION_BPS,
    horizon_s=HORIZON_MAX_S,
    fraicheur_ms=FRAICHEUR_MAX_MS,
    latence_ms=LATENCE_MS,
    fees_ar_bps=FEES_AR_BPS,
    ecart_max=ECART_MAX_ENTREE_BPS,
    depth_by_coin: dict[str, list[tuple[float, float]]] | None = None,
    depth_freshness_ms=DEPTH_FRESHNESS_MS,
    notional_usd=NOTIONAL_USD,
    direction_multiplier: int = 1,
    min_executable_edge_bps=MIN_EXECUTABLE_EDGE_BPS,
    max_observation_gap_ms=MAX_OBSERVATION_GAP_MS,
    diagnostics: dict | None = None,
) -> list[dict]:
    """Replay causally: detect, wait, execute, then close on a later quote."""
    counters = {
        "candidate_detections": 0,
        "rejected_non_positive_executable_edge": 0,
        "rejected_entry_depth": 0,
        "exits_deferred_depth": 0,
        "positions_left_open": 0,
        "positions_closed": 0,
        "positions_invalidated_gap": 0,
        "pending_invalidated_gap": 0,
    }
    invalidated_positions: list[dict] = []
    residual_positions: list[dict] = []
    trades: list[dict] = []
    for coin, raw_events in series.items():
        if str(coin).startswith("_"):
            continue
        events = sorted(raw_events, key=lambda event: event[0])
        latest = {"HL": None, "BIN": None}
        pending = None
        position = None
        previous_observation_ms = None
        for event in events:
            ts, venue = event[0], event[1]
            if (
                previous_observation_ms is not None
                and float(ts) - float(previous_observation_ms) > float(max_observation_gap_ms)
            ):
                if pending is not None:
                    counters["pending_invalidated_gap"] += 1
                    pending = None
                if position is not None:
                    counters["positions_invalidated_gap"] += 1
                    invalidated_positions.append({
                        "reason": "OBSERVATION_GAP",
                        "coin": str(coin),
                        "ts_detect": position["ts_detect"],
                        "ts_in": position["ts_in"],
                        "last_observed_ms": previous_observation_ms,
                        "next_observed_ms": ts,
                        "gap_ms": float(ts) - float(previous_observation_ms),
                        "sens": position["sens"],
                        "basis_in_bps": round(float(position["basis_in"]), 4),
                        "exit_pending_reason": position.get("exit_pending_reason"),
                    })
                    position = None
                latest = {"HL": None, "BIN": None}
            previous_observation_ms = ts
            if venue == "ATOMIC":
                if len(event) != 6:
                    continue
                _, _, hl_bid, hl_ask, bin_bid, bin_ask = event
                latest["HL"] = (ts, hl_bid, hl_ask)
                latest["BIN"] = (ts, bin_bid, bin_ask)
            elif venue in latest and len(event) == 4:
                _, _, bid, ask = event
                latest[venue] = (ts, bid, ask)
            else:
                continue
            hl, bn = latest["HL"], latest["BIN"]
            if hl is None or bn is None:
                continue
            if ts - hl[0] > fraicheur_ms or ts - bn[0] > fraicheur_ms:
                continue
            basis = _basis_bps(hl, bn)
            if basis is None:
                continue

            if position is None:
                if pending is not None:
                    if ts < pending["execute_after_ms"]:
                        continue
                    same_direction = (1 if basis > 0 else -1) == pending["sens"]
                    still_executable = seuil_entree <= abs(basis) <= ecart_max
                    if not (same_direction and still_executable):
                        pending = None
                        continue
                    convergence_edge = _convergence_edge_bps(
                        hl,
                        bn,
                        sens=pending["sens"],
                        fees_ar_bps=float(fees_ar_bps),
                    )
                    if convergence_edge <= float(min_executable_edge_bps):
                        counters["rejected_non_positive_executable_edge"] += 1
                        pending = None
                        continue
                    entry_depth = None
                    if depth_by_coin is not None:
                        entry_depth = _depth_at(
                            depth_by_coin.get(str(coin), []),
                            ts,
                            freshness_ms=float(depth_freshness_ms),
                        )
                        if (
                            entry_depth is None
                            or float(entry_depth["capacity_usd"]) < float(notional_usd)
                        ):
                            counters["rejected_entry_depth"] += 1
                            pending = None
                            continue
                    position = {
                        "ts_detect": pending["ts_detect"],
                        "basis_detect": pending["basis_detect"],
                        "hl_detect": pending["hl_detect"],
                        "bn_detect": pending["bn_detect"],
                        "ts_in": ts,
                        "basis_in": basis,
                        "sens": pending["sens"] * (1 if direction_multiplier >= 0 else -1),
                        "hl_in": hl,
                        "bn_in": bn,
                        "entry_depth": entry_depth,
                        "entry_convergence_edge_bps": convergence_edge,
                        "exit_pending_reason": None,
                    }
                    pending = None
                    continue
                if seuil_entree <= abs(basis) <= ecart_max:
                    counters["candidate_detections"] += 1
                    sens = 1 if basis > 0 else -1
                    if _convergence_edge_bps(
                        hl,
                        bn,
                        sens=sens,
                        fees_ar_bps=float(fees_ar_bps),
                    ) <= float(min_executable_edge_bps):
                        counters["rejected_non_positive_executable_edge"] += 1
                        continue
                    pending = {
                        "ts_detect": ts,
                        "execute_after_ms": ts + max(0.0, float(latence_ms)),
                        "basis_detect": basis,
                        "sens": sens,
                        "hl_detect": hl,
                        "bn_detect": bn,
                    }
                continue

            age_s = (ts - position["ts_in"]) / 1000.0
            converged = abs(basis) <= seuil_sortie
            expired = age_s >= horizon_s
            stopped = abs(basis) >= abs(position["basis_in"]) + stop_bps
            exit_reason = position.get("exit_pending_reason")
            if exit_reason is None:
                exit_reason = (
                    "CONVERGENCE" if converged else ("STOP" if stopped else ("AGE" if expired else None))
                )
            if exit_reason is None:
                continue

            exit_depth = None
            if depth_by_coin is not None:
                exit_depth = _depth_at(
                    depth_by_coin.get(str(coin), []),
                    ts,
                    freshness_ms=float(depth_freshness_ms),
                )
                if exit_depth is None or float(exit_depth["capacity_usd"]) < float(notional_usd):
                    position["exit_pending_reason"] = exit_reason
                    counters["exits_deferred_depth"] += 1
                    continue

            executable_before_fees = _net_trade_bps(
                position["hl_in"], position["bn_in"], hl, bn,
                sens=position["sens"], fees_ar_bps=0.0,
            )
            gross_at_detection = _mid_trade_bps(
                position["hl_detect"], position["bn_detect"], hl, bn,
                sens=position["sens"],
            )
            gross_at_entry = _mid_trade_bps(
                position["hl_in"], position["bn_in"], hl, bn,
                sens=position["sens"],
            )
            raw_latency_impact = gross_at_detection - gross_at_entry
            raw_spread_impact = gross_at_entry - executable_before_fees
            latency_cost = max(0.0, raw_latency_impact)
            spread_cost = max(0.0, raw_spread_impact)
            depth_observed = bool(
                position.get("entry_depth") is not None
                and exit_depth is not None
                and min(
                    float(position["entry_depth"]["capacity_usd"]),
                    float(exit_depth["capacity_usd"]),
                ) >= float(notional_usd)
            )
            # BBO already includes the crossed spread.  When the recorded
            # minimum capacity of all four required sides covers the full
            # notional at both entry and exit, incremental L2 slippage is
            # observed as exactly zero rather than guessed.
            slippage_bps = 0.0 if depth_observed else None
            net = executable_before_fees - float(fees_ar_bps) - float(slippage_bps or 0.0)
            gross_reconciled = (
                net + float(fees_ar_bps) + spread_cost + latency_cost + float(slippage_bps or 0.0)
            )
            fees_usd = float(fees_ar_bps) / 1e4 * float(notional_usd)
            spread_usd = spread_cost / 1e4 * float(notional_usd)
            slippage_usd = float(slippage_bps or 0.0) / 1e4 * float(notional_usd)
            latency_usd = latency_cost / 1e4 * float(notional_usd)
            spread_zero_reason = (
                ZeroCostReason.NOT_APPLICABLE
                if spread_cost == 0.0 and raw_spread_impact < 0.0
                else ZeroCostReason.MEASURED_ZERO
                if spread_cost == 0.0
                else None
            )
            latency_zero_reason = (
                ZeroCostReason.NOT_APPLICABLE
                if latency_cost == 0.0 and raw_latency_impact < 0.0
                else ZeroCostReason.MEASURED_ZERO
                if latency_cost == 0.0
                else None
            )
            slippage_zero_reason = (
                ZeroCostReason.MEASURED_ZERO
                if depth_observed
                else ZeroCostReason.MISSING_UNMEASURABLE
            )
            cost_component_receipts = {
                "fees": CostComponentReceipt(
                    component="fees",
                    amount_usd=fees_usd,
                    zero_reason=(
                        ZeroCostReason.MEASURED_ZERO if fees_usd == 0.0 else None
                    ),
                    formula_id="cross_venue.round_trip_fee.v1",
                    reality_model_version=_CROSS_REALITY_MODEL_VERSION,
                    provenance_ids=(
                        "fee.taker.hyperliquid.bps",
                        "fee.taker.binance.bps",
                        "cross_venue.paper_notional_usd",
                    ),
                ).as_dict(),
                "spread": CostComponentReceipt(
                    component="spread",
                    amount_usd=spread_usd,
                    zero_reason=spread_zero_reason,
                    formula_id="cross_venue.executable_bid_ask_spread.v1",
                    reality_model_version=_CROSS_REALITY_MODEL_VERSION,
                    provenance_ids=("entry_bbo.bid_ask", "exit_bbo.bid_ask"),
                ).as_dict(),
                "slippage": CostComponentReceipt(
                    component="slippage",
                    amount_usd=slippage_usd,
                    zero_reason=slippage_zero_reason,
                    formula_id="cross_venue.full_depth_capacity.v1",
                    reality_model_version=_CROSS_REALITY_MODEL_VERSION,
                    provenance_ids=("entry_capacity_usd", "exit_capacity_usd"),
                ).as_dict(),
                "latency": CostComponentReceipt(
                    component="latency",
                    amount_usd=latency_usd,
                    zero_reason=latency_zero_reason,
                    formula_id="cross_venue.causal_entry_latency.v1",
                    reality_model_version=_CROSS_REALITY_MODEL_VERSION,
                    provenance_ids=("ts_detect", "ts_in"),
                ).as_dict(),
            }
            trade_id = _trade_id(
                coin=str(coin), ts_detect=position["ts_detect"],
                ts_in=position["ts_in"], ts_out=ts, sens=position["sens"],
            )
            trades.append({
                "trade_id": trade_id,
                "coin": coin,
                "ts_detect": position["ts_detect"],
                "ts_in": position["ts_in"],
                "ts_out": ts,
                "age_s": round(age_s, 1),
                "basis_detect_bps": round(position["basis_detect"], 4),
                "basis_in_bps": round(position["basis_in"], 4),
                "basis_out_bps": round(basis, 4),
                "entry_convergence_edge_bps": round(
                    float(position["entry_convergence_edge_bps"]), 4
                ),
                "gross_signal_bps": round(gross_at_detection, 4),
                "gross_entry_bps": round(gross_at_entry, 4),
                "gross_reconciled_bps": round(gross_reconciled, 4),
                "fees_bps": round(float(fees_ar_bps), 4),
                "spread_cost_bps": round(spread_cost, 4),
                "slippage_bps": None if slippage_bps is None else round(slippage_bps, 4),
                "latency_cost_bps": round(latency_cost, 4),
                "cost_component_receipts": cost_component_receipts,
                "slippage_zero_reason": slippage_zero_reason.value,
                "latency_zero_reason": (
                    latency_zero_reason.value if latency_zero_reason is not None else None
                ),
                "raw_latency_impact_bps": round(raw_latency_impact, 4),
                "raw_spread_impact_bps": round(raw_spread_impact, 4),
                "net_bps": round(net, 4),
                "net_usd": round(net / 1e4 * float(notional_usd), 6),
                "notional_usd": float(notional_usd),
                "entry_capacity_usd": (
                    round(float(position["entry_depth"]["capacity_usd"]), 6)
                    if position.get("entry_depth") is not None else None
                ),
                "exit_capacity_usd": (
                    round(float(exit_depth["capacity_usd"]), 6) if exit_depth else None
                ),
                "depth_freshness_ms": float(depth_freshness_ms),
                "two_leg": True,
                "LIQUIDATABLE_NET": depth_observed,
                "sortie": exit_reason,
            })
            counters["positions_closed"] += 1
            position = None
        if position is not None:
            counters["positions_left_open"] += 1
            residual_positions.append({
                "reason": "END_OF_DATA",
                "coin": str(coin),
                "ts_detect": position["ts_detect"],
                "ts_in": position["ts_in"],
                "last_observed_ms": previous_observation_ms,
                "sens": position["sens"],
                "basis_in_bps": round(float(position["basis_in"]), 4),
                "last_basis_bps": round(float(basis), 4),
                "exit_pending_reason": position.get("exit_pending_reason"),
            })
    if diagnostics is not None:
        diagnostics.clear()
        diagnostics.update(counters)
        diagnostics["invalidated_positions"] = invalidated_positions
        diagnostics["residual_positions"] = residual_positions
    return trades


def _pf(nets):
    positive = sum(value for value in nets if value > 0)
    negative = sum(-value for value in nets if value < 0)
    return round(positive / negative, 3) if negative > 0 else (float("inf") if positive > 0 else 0.0)


def _dd_usd(trades):
    cumulative = peak = 0.0
    drawdown = 0.0
    for trade in sorted(trades, key=lambda value: value["ts_out"]):
        cumulative += trade["net_usd"]
        peak = max(peak, cumulative)
        drawdown = min(drawdown, cumulative - peak)
    return round(drawdown, 6)


def _summary(trades: list[dict]) -> dict:
    count = len(trades)
    ids = sorted({str(trade.get("trade_id")) for trade in trades if trade.get("trade_id")})
    net = sum(float(trade.get("net_usd") or 0.0) for trade in trades)
    def component_usd(trade, key):
        return (
            float(trade.get(key) or 0.0)
            / 1e4
            * float(trade.get("notional_usd") or NOTIONAL_USD)
        )

    slippage_measured = bool(
        count and all(trade.get("slippage_bps") is not None for trade in trades)
    )
    result = {
        "n_trades": count,
        "positions_ouvertes": count,
        "positions_fermees": count,
        "gross_pnl_usd": round(sum(component_usd(t, "gross_reconciled_bps") for t in trades), 6),
        "fees_usd": round(sum(component_usd(t, "fees_bps") for t in trades), 6),
        "spread_cost_usd": round(sum(component_usd(t, "spread_cost_bps") for t in trades), 6),
        "slippage_cost_usd": (
            round(sum(component_usd(t, "slippage_bps") for t in trades), 6)
            if slippage_measured else None
        ),
        "latency_cost_usd": round(sum(component_usd(t, "latency_cost_bps") for t in trades), 6),
        "net_total_usd": round(net, 6),
        "roi_pct": round(net / 1000.0 * 100.0, 6),
        "hit_rate": round(sum(1 for t in trades if float(t.get("net_usd") or 0.0) > 0) / count, 6) if count else 0.0,
        "profit_factor": _pf([float(t.get("net_bps") or 0.0) for t in trades]),
        "max_drawdown_usd": abs(_dd_usd(trades)),
        "trade_ids_count": len(ids),
        "trade_ids_sha256": hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest(),
        "duplicate_trade_ids": count - len(ids),
        "LIQUIDATABLE_NET": bool(count and all(t.get("LIQUIDATABLE_NET") is True for t in trades)),
        "all_positions_two_leg_closed": bool(count and all(t.get("two_leg") is True for t in trades)),
    }
    components = (
        result["fees_usd"],
        result["spread_cost_usd"],
        result["slippage_cost_usd"],
        result["latency_cost_usd"],
    )
    result["economic_reconciled"] = bool(
        all(value is not None for value in components)
        and abs(result["gross_pnl_usd"] - sum(components) - result["net_total_usd"]) <= 1e-4
    )
    result["LIQUIDATABLE_NET"] = bool(
        result["LIQUIDATABLE_NET"] and result["economic_reconciled"]
    )
    return result


def _objective_segment(trades: list[dict], *, post_freeze: bool = False) -> dict:
    summary = _summary(trades)
    return {
        "gross_pnl_usd": summary["gross_pnl_usd"],
        "fees_usd": summary["fees_usd"],
        "spread_cost_usd": summary["spread_cost_usd"],
        "slippage_cost_usd": summary["slippage_cost_usd"],
        "latency_cost_usd": summary["latency_cost_usd"],
        "net_pnl_usd": summary["net_total_usd"],
        "sample_count": summary["n_trades"],
        "trade_ids_count": summary["trade_ids_count"],
        "trade_ids_sha256": summary["trade_ids_sha256"],
        "duplicate_trade_ids": summary["duplicate_trade_ids"],
        "no_lookahead": True,
        "post_freeze": bool(post_freeze and summary["n_trades"] > 0),
        "liquidatable_net": summary["LIQUIDATABLE_NET"],
    }


def construire_preuves_temporelles(
    trades: list[dict],
    placebo_trades: list[dict],
    *,
    frozen_at_ms: float,
    in_sample_fraction: float = 0.70,
) -> dict:
    """Create immutable historical OOS and genuine post-freeze evidence."""

    ordered = sorted(trades, key=lambda row: (row["ts_detect"], row["trade_id"]))
    historical = [row for row in ordered if float(row["ts_detect"]) <= float(frozen_at_ms)]
    forward = [row for row in ordered if float(row["ts_detect"]) > float(frozen_at_ms)]
    cut = min(len(historical), max(1, int(len(historical) * in_sample_fraction))) if historical else 0
    oos = historical[cut:]

    placebo_ordered = sorted(
        (row for row in placebo_trades if float(row["ts_detect"]) <= float(frozen_at_ms)),
        key=lambda row: (row["ts_detect"], row["trade_id"]),
    )
    placebo_cut = (
        min(len(placebo_ordered), max(1, int(len(placebo_ordered) * in_sample_fraction)))
        if placebo_ordered else 0
    )
    placebo_oos = placebo_ordered[placebo_cut:]
    candidate_segment = _objective_segment(oos)
    placebo_segment = _objective_segment(placebo_oos)
    return {
        "is": _objective_segment(historical[:cut]),
        "oos": candidate_segment,
        "forward": _objective_segment(forward, post_freeze=True),
        "placebos": {
            "beaten": bool(
                candidate_segment["sample_count"]
                and placebo_segment["sample_count"]
                and candidate_segment["net_pnl_usd"] > placebo_segment["net_pnl_usd"]
            ),
            "candidate_net_usd": candidate_segment["net_pnl_usd"],
            "placebo_net_usd": placebo_segment["net_pnl_usd"],
            "candidate_count": candidate_segment["sample_count"],
            "placebo_count": placebo_segment["sample_count"],
        },
    }


def walk_forward_protocol_signature() -> dict:
    """Stable signature used to recover the same physical freeze later."""

    grid_material = json.dumps(CROSS_WALK_FORWARD_GRID, sort_keys=True, separators=(",", ":"))
    return {
        "calibration_protocol": CROSS_WALK_FORWARD_PROTOCOL,
        "grid_sha256": hashlib.sha256(grid_material.encode("utf-8")).hexdigest(),
        "train_fraction": CROSS_TRAIN_FRACTION,
        "validation_fraction": CROSS_VALIDATION_FRACTION,
        "purge_ms": CROSS_PURGE_MS,
        "minimum_train_trades": CROSS_MIN_TRAIN_TRADES,
        "source_mode": CERTIFIED_CROSS_SOURCE_MODE,
        "four_fill_contract_version": FOUR_FILL_CONTRACT_VERSION,
        "capacity_contract": "minimum_four_bbo_top_levels_usd",
    }


def calculer_bornes_walk_forward(series: dict) -> dict:
    """Choose chronological boundaries from timestamps, never from returns."""

    timestamps = sorted(
        {
            float(event[0])
            for coin, events in series.items()
            if not str(coin).startswith("_")
            for event in events
            if event
        }
    )
    if len(timestamps) < 30:
        return {
            "status": "INSUFFICIENT_TIMESTAMPS",
            "observation_timestamps": len(timestamps),
        }
    train_index = max(0, min(len(timestamps) - 3, int(len(timestamps) * CROSS_TRAIN_FRACTION) - 1))
    validation_index = max(
        train_index + 1,
        min(
            len(timestamps) - 2,
            int(len(timestamps) * (CROSS_TRAIN_FRACTION + CROSS_VALIDATION_FRACTION)) - 1,
        ),
    )
    bounds = {
        "status": "READY",
        "observation_timestamps": len(timestamps),
        "first_observed_ms": timestamps[0],
        "train_end_ms": timestamps[train_index],
        "validation_start_ms": timestamps[train_index] + CROSS_PURGE_MS,
        "validation_end_ms": timestamps[validation_index],
        "oos_start_ms": timestamps[validation_index] + CROSS_PURGE_MS,
        "calibration_data_end_ms": timestamps[-1],
        "purge_ms": CROSS_PURGE_MS,
    }
    invalid_purged_ranges = (
        bounds["validation_start_ms"] > bounds["validation_end_ms"]
        or bounds["oos_start_ms"] > bounds["calibration_data_end_ms"]
    )
    if invalid_purged_ranges:
        bounds["status"] = "INSUFFICIENT_DURATION_FOR_PURGED_SPLITS"
        bounds["observed_span_ms"] = timestamps[-1] - timestamps[0]
        bounds["required_additional_ms"] = max(
            0.0,
            bounds["validation_start_ms"] - bounds["validation_end_ms"],
            bounds["oos_start_ms"] - bounds["calibration_data_end_ms"],
        )
    return bounds


def _slice_observations(
    values_by_coin: dict,
    *,
    start_ms: float | None = None,
    end_ms: float | None = None,
) -> dict:
    sliced = {}
    for coin, values in values_by_coin.items():
        if str(coin).startswith("_"):
            continue
        rows = [
            value
            for value in values
            if (start_ms is None or float(value[0]) >= float(start_ms))
            and (end_ms is None or float(value[0]) <= float(end_ms))
        ]
        if rows:
            sliced[coin] = rows
    return sliced


def _training_rank(summary: dict, parameters: dict) -> tuple:
    count = int(summary.get("n_trades") or 0)
    net = float(summary.get("net_total_usd") or 0.0)
    pf = float(summary.get("profit_factor") or 0.0)
    if pf == float("inf"):
        pf = 1000.0
    eligible = bool(
        count >= CROSS_MIN_TRAIN_TRADES
        and summary.get("LIQUIDATABLE_NET") is True
        and net > 0.0
        and pf > 1.2
    )
    # Net is the primary economic target.  The remaining fields provide a
    # deterministic tie-break without consulting validation or OOS returns.
    return (
        int(eligible),
        round(net, 12),
        round(min(pf, 1000.0), 12),
        count,
        json.dumps(parameters, sort_keys=True, separators=(",", ":")),
    )


def selectionner_parametres_train(
    train_series: dict,
    train_depth: dict,
    *,
    grid: tuple[dict, ...] = CROSS_WALK_FORWARD_GRID,
    replay_fn=None,
) -> dict:
    """Select a candidate using training observations only."""

    replay = replay_fn or backtester
    candidates = []
    for parameters in grid:
        diagnostics: dict = {}
        trades = replay(
            train_series,
            depth_by_coin=train_depth,
            diagnostics=diagnostics,
            **parameters,
        )
        summary = _summary(trades)
        eligible = _training_rank(summary, parameters)[0] == 1
        candidates.append(
            {
                "parameters": dict(parameters),
                "summary": summary,
                "eligible": eligible,
                "diagnostics": diagnostics,
            }
        )
    if not candidates:
        return {"status": "NO_GRID", "selected": None, "candidates": []}
    best = max(
        candidates,
        key=lambda row: _training_rank(row["summary"], row["parameters"]),
    )
    return {
        "status": "SELECTED" if best["eligible"] else "KILL_TRAIN",
        "selected": best,
        "candidate_count": len(candidates),
        "eligible_candidate_count": sum(1 for row in candidates if row["eligible"]),
        "candidates": candidates,
    }


def calibrer_walk_forward(series: dict, depth_by_coin: dict) -> dict:
    """Compute boundaries and select parameters without reading later returns."""

    bounds = calculer_bornes_walk_forward(series)
    if bounds.get("status") != "READY":
        return {"status": bounds.get("status"), "bounds": bounds, "selection": None}
    train_series = _slice_observations(series, end_ms=bounds["train_end_ms"])
    train_depth = _slice_observations(depth_by_coin, end_ms=bounds["train_end_ms"])
    selection = selectionner_parametres_train(train_series, train_depth)
    return {
        "status": selection["status"],
        "bounds": bounds,
        "selection": selection,
    }


def _replay_segment(
    series: dict,
    depth_by_coin: dict,
    parameters: dict,
    *,
    start_ms: float | None,
    end_ms: float | None,
    direction_multiplier: int = 1,
) -> tuple[list[dict], dict]:
    segment_series = _slice_observations(series, start_ms=start_ms, end_ms=end_ms)
    segment_depth = _slice_observations(depth_by_coin, start_ms=start_ms, end_ms=end_ms)
    diagnostics: dict = {}
    trades = backtester(
        segment_series,
        depth_by_coin=segment_depth,
        direction_multiplier=direction_multiplier,
        diagnostics=diagnostics,
        **parameters,
    )
    return trades, diagnostics


def evaluer_walk_forward_gelé(
    series: dict,
    depth_by_coin: dict,
    *,
    frozen_parameters: dict,
    frozen_at_ms: float,
) -> dict:
    """Evaluate an already-selected candidate on disjoint causal segments."""

    bounds = frozen_parameters.get("walk_forward_bounds")
    parameters = frozen_parameters.get("selected_strategy_parameters")
    if not isinstance(bounds, dict) or bounds.get("status") != "READY" or not isinstance(parameters, dict):
        return {"status": "INVALID_OR_INCOMPLETE_FREEZE"}

    ranges = {
        "train": (bounds.get("first_observed_ms"), bounds["train_end_ms"]),
        "validation": (bounds["validation_start_ms"], bounds["validation_end_ms"]),
        "oos": (bounds["oos_start_ms"], bounds["calibration_data_end_ms"]),
        "forward": (
            max(float(bounds["calibration_data_end_ms"]), float(frozen_at_ms)) + 1.0,
            None,
        ),
    }
    segments = {}
    trades_by_segment = {}
    diagnostics = {}
    for name, (start_ms, end_ms) in ranges.items():
        trades, counters = _replay_segment(
            series,
            depth_by_coin,
            parameters,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        trades_by_segment[name] = trades
        diagnostics[name] = counters
        segments[name] = _summary(trades)

    placebo_oos, placebo_diagnostics = _replay_segment(
        series,
        depth_by_coin,
        parameters,
        start_ms=ranges["oos"][0],
        end_ms=ranges["oos"][1],
        direction_multiplier=-1,
    )
    placebo_summary = _summary(placebo_oos)
    train_ok = bool(frozen_parameters.get("training_selection_eligible") is True)
    validation_ok = bool(
        segments["validation"]["n_trades"] >= 4
        and segments["validation"]["net_total_usd"] > 0
        and segments["validation"]["profit_factor"] > 1.0
    )
    oos_ok = bool(
        segments["oos"]["n_trades"] >= 4
        and segments["oos"]["net_total_usd"] > 0
        and segments["oos"]["profit_factor"] > 1.0
        and segments["oos"]["net_total_usd"] > placebo_summary["net_total_usd"]
    )
    return {
        "status": "ELIGIBLE_FOR_FORWARD" if train_ok and validation_ok and oos_ok else "KILL_HISTORICAL",
        "protocol": walk_forward_protocol_signature(),
        "bounds": bounds,
        "selected_strategy_parameters": dict(parameters),
        "training_selection_eligible": train_ok,
        "validation_eligible": validation_ok,
        "oos_eligible": oos_ok,
        "segments": segments,
        "diagnostics": diagnostics,
        "placebo_oos": placebo_summary,
        "placebo_diagnostics": placebo_diagnostics,
        "trades": trades_by_segment,
    }


def preuves_temporelles_walk_forward(walk_forward: dict) -> dict:
    """Map strict walk-forward results to the shared objective contract."""

    segments = walk_forward.get("segments") if isinstance(walk_forward.get("segments"), dict) else {}
    oos_summary = segments.get("oos") if isinstance(segments.get("oos"), dict) else {}
    forward_summary = segments.get("forward") if isinstance(segments.get("forward"), dict) else {}
    placebo = walk_forward.get("placebo_oos") if isinstance(walk_forward.get("placebo_oos"), dict) else {}

    def objective(summary: dict, *, post_freeze: bool = False) -> dict:
        count = int(summary.get("n_trades") or 0)
        return {
            "gross_pnl_usd": summary.get("gross_pnl_usd"),
            "fees_usd": summary.get("fees_usd"),
            "spread_cost_usd": summary.get("spread_cost_usd"),
            "slippage_cost_usd": summary.get("slippage_cost_usd"),
            "latency_cost_usd": summary.get("latency_cost_usd"),
            "net_pnl_usd": float(summary.get("net_total_usd") or 0.0),
            "sample_count": count,
            "trade_ids_count": summary.get("trade_ids_count"),
            "trade_ids_sha256": summary.get("trade_ids_sha256"),
            "duplicate_trade_ids": summary.get("duplicate_trade_ids"),
            "no_lookahead": True,
            "post_freeze": bool(post_freeze and count > 0),
            "liquidatable_net": summary.get("LIQUIDATABLE_NET") is True,
        }

    return {
        "is": objective(segments.get("train", {})),
        "validation": objective(segments.get("validation", {})),
        "oos": objective(oos_summary),
        "forward": objective(forward_summary, post_freeze=True),
        "placebos": {
            "beaten": bool(
                oos_summary.get("n_trades")
                and placebo.get("n_trades")
                and float(oos_summary.get("net_total_usd") or 0.0)
                > float(placebo.get("net_total_usd") or 0.0)
            ),
            "candidate_net_usd": float(oos_summary.get("net_total_usd") or 0.0),
            "placebo_net_usd": float(placebo.get("net_total_usd") or 0.0),
            "candidate_count": int(oos_summary.get("n_trades") or 0),
            "placebo_count": int(placebo.get("n_trades") or 0),
        },
    }


def diagnostiquer_hypothese_walk_forward(walk_forward: dict) -> dict:
    """Explain whether the frozen mechanism survives without mining its control.

    The inverted replay is a falsification control observed on the same OOS
    interval.  A positive control is useful evidence that the original economic
    hypothesis may have the wrong sign, but it is never a strategy eligible for
    promotion after looking at that interval.
    """

    segments = walk_forward.get("segments") if isinstance(walk_forward.get("segments"), dict) else {}
    train = segments.get("train") if isinstance(segments.get("train"), dict) else {}
    validation = segments.get("validation") if isinstance(segments.get("validation"), dict) else {}
    oos = segments.get("oos") if isinstance(segments.get("oos"), dict) else {}
    forward = segments.get("forward") if isinstance(segments.get("forward"), dict) else {}
    control = walk_forward.get("placebo_oos") if isinstance(walk_forward.get("placebo_oos"), dict) else {}

    current_status = str(walk_forward.get("status") or "UNKNOWN")
    killed = current_status != "ELIGIBLE_FOR_FORWARD"
    control_positive = bool(
        int(control.get("n_trades") or 0) > 0
        and float(control.get("net_total_usd") or 0.0) > 0.0
        and float(control.get("profit_factor") or 0.0) > 1.0
    )

    def compact(summary: dict) -> dict:
        return {
            "sample_count": int(summary.get("n_trades") or 0),
            "net_pnl_usd": float(summary.get("net_total_usd") or 0.0),
            "profit_factor": float(summary.get("profit_factor") or 0.0),
        }

    return {
        "hypothesis_id": "CROSS_VENUE_BASIS_CONVERGENCE_V2",
        "frozen_mechanism_status": "KILL" if killed else "ELIGIBLE_FOR_FORWARD",
        "source_walk_forward_status": current_status,
        "train": compact(train),
        "validation": compact(validation),
        "oos": compact(oos),
        "forward": compact(forward),
        "inverted_direction_control": {
            **compact(control),
            "positive_oos": control_positive,
            "promotable": False,
            "non_promotion_reason": "OOS_CONTROL_NOT_A_PREDECLARED_STRATEGY",
        },
        "new_mechanism_required": killed,
        "next_action": (
            "DECLARE_FREEZE_AND_TEST_A_NEW_DIRECTIONAL_MECHANISM_ON_FUTURE_DATA"
            if killed and control_positive
            else "COLLECT_FORWARD_WITH_FROZEN_MECHANISM"
            if not killed
            else "KILL_CURRENT_MECHANISM_AND_FORMULATE_A_MATERIALLY_NEW_HYPOTHESIS"
        ),
        "retrospective_direction_switch_forbidden": True,
    }


def juger(trades: list[dict]) -> dict:
    count = len(trades)
    summary = _summary(trades)
    if count < 8:
        return {**summary, "verdict": "INSUFFISANT", "motif": "moins de 8 trades fermes"}
    nets = [trade["net_bps"] for trade in trades]
    ordered = sorted(trades, key=lambda trade: trade["ts_out"])
    middle = count // 2
    first = [trade["net_bps"] for trade in ordered[:middle]]
    second = [trade["net_bps"] for trade in ordered[middle:]]
    best = max(range(count), key=lambda index: nets[index])
    without_best = [value for index, value in enumerate(nets) if index != best]
    median = statistics.median(nets)
    median_first = statistics.median(first)
    median_second = statistics.median(second)
    median_loo = statistics.median(without_best)
    profit_factor = _pf(nets)
    armed = median_first > 0 and median_second > 0 and profit_factor > 1.2 and median_loo > 0
    return {
        **summary,
        "verdict": "ARME_COHORTE" if armed else "KILL",
        "net_median_bps": round(median, 4),
        "net_moyen_bps": round(sum(nets) / count, 4),
        "net_median_usd": round(statistics.median([t["net_usd"] for t in trades]), 6),
        "pf": profit_factor,
        "dd_usd": _dd_usd(trades),
        "median_moitie1_bps": round(median_first, 4),
        "median_moitie2_bps": round(median_second, 4),
        "median_sans_meilleur_bps": round(median_loo, 4),
        "regle_arme": "net+ 2 moities ET pf>1.2 ET positif sans meilleur trade",
    }


def _lignes(source):
    opener = gzip.open if str(source).endswith(".gz") else open
    try:
        with opener(source, "rt", encoding="utf-8", errors="ignore") as handle:
            yield from handle
    except OSError:
        return


def collecter_profondeur(root: Path) -> tuple[dict[str, list[tuple[float, float]]], dict]:
    """Load the recorded four-side minimum top-book capacity per coin.

    ``taille_min_usd`` is produced by ``collecter_carnet.py`` as the minimum
    USD capacity across HL bid/ask and Binance bid/ask.  It therefore proves
    that a four-fill paper round-trip of no more than that notional fits at
    the already-recorded BBO, with zero incremental depth slippage.
    """

    source = root / "runtime" / "data" / "carnet_venues.jsonl"
    by_coin: dict[str, list[tuple[float, float]]] = {}
    lines_read = invalid = 0
    for line in _lignes(source):
        lines_read += 1
        try:
            row = json.loads(line)
            coin = str(row["coin"]).upper()
            timestamp = float(row["collecte_ts"])
            timestamp_ms = timestamp * 1000.0 if timestamp < 10_000_000_000 else timestamp
            capacity = float(row["taille_min_usd"])
            if timestamp_ms <= 0 or capacity <= 0:
                raise ValueError
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid += 1
            continue
        by_coin.setdefault(coin, []).append((timestamp_ms, capacity))
    for rows in by_coin.values():
        rows.sort()
    return by_coin, {
        "source": source.relative_to(root).as_posix(),
        "lines_read": lines_read,
        "invalid_rows": invalid,
        "coins": len(by_coin),
        "capacity_definition": "minimum USD capacity across HL/BIN bid/ask",
    }


def collecter_carnet_series(
    root: Path,
    *,
    coins: tuple[str, ...] | None = None,
) -> tuple[dict[str, list[tuple]], dict[str, list[tuple[float, float]]], dict]:
    """Load atomic HL/Binance BBO plus four-side capacity observations.

    Each source row was produced from one bounded collector pass and contains
    both executable books.  Replaying this row avoids joining unrelated BBO
    clocks while preserving the exact observed capacity.
    """

    source = root / "runtime" / "data" / "carnet_venues.jsonl"
    allowed = {coin.upper() for coin in coins} if coins else None
    series: dict[str, list[tuple]] = {}
    depth: dict[str, list[tuple[float, float]]] = {}
    seen: set[tuple[str, float]] = set()
    lines_read = invalid = duplicates = 0
    first_ms = last_ms = None
    for line in _lignes(source):
        lines_read += 1
        try:
            row = json.loads(line)
            coin = str(row["coin"]).upper()
            if allowed is not None and coin not in allowed:
                continue
            timestamp = float(row["collecte_ts"])
            timestamp_ms = timestamp * 1000.0 if timestamp < 10_000_000_000 else timestamp
            hl_bid = float(row["hl_bid"])
            hl_ask = float(row["hl_ask"])
            bin_bid = float(row["bin_bid"])
            bin_ask = float(row["bin_ask"])
            capacity = float(row["taille_min_usd"])
            if not (
                timestamp_ms > 0
                and 0 < hl_bid <= hl_ask
                and 0 < bin_bid <= bin_ask
                and capacity > 0
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid += 1
            continue
        key = (coin, timestamp_ms)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        series.setdefault(coin, []).append(
            (timestamp_ms, "ATOMIC", hl_bid, hl_ask, bin_bid, bin_ask)
        )
        depth.setdefault(coin, []).append((timestamp_ms, capacity))
        first_ms = timestamp_ms if first_ms is None else min(first_ms, timestamp_ms)
        last_ms = timestamp_ms if last_ms is None else max(last_ms, timestamp_ms)
    for rows in series.values():
        rows.sort()
    for rows in depth.values():
        rows.sort()
    return series, depth, {
        "source": source.relative_to(root).as_posix(),
        "source_mode": "ATOMIC_FOUR_SIDE_BOOK",
        "lines_read": lines_read,
        "valid_snapshots": len(seen),
        "invalid_rows": invalid,
        "duplicates_rejected": duplicates,
        "coins": len(series),
        "first_observed_ms": first_ms,
        "last_observed_ms": last_ms,
        "stopped_reason": "COMPLETED",
    }


def collecter_series(
    root: Path,
    *,
    ds_ms: float = 1000.0,
    coins=COINS_COMMUNS,
    budget_s: float = 0.0,
    current_only: bool = False,
) -> dict:
    """Stream local BBO sources with bounded work and explicit stop reason."""
    data_dir = root / "runtime" / "data"
    sources: list[Path | str] = [data_dir / "bbo_tape.jsonl"]
    if not current_only:
        sources += sorted(glob.glob(str(data_dir / "bbo_shards" / "*.jsonl.gz")))
        sources += sorted(glob.glob(str(data_dir / "bbo_shards_archive" / "*.jsonl.gz")))
        if (data_dir / "bbo_tape.jsonl.prev").exists():
            sources.append(data_dir / "bbo_tape.jsonl.prev")
    target_coins = set(coins)
    series = {coin: [] for coin in coins}
    last_bucket: dict[tuple[str, str], int] = {}
    started = time.monotonic()
    lines_read = 0
    sources_read = 0
    stopped_reason = "COMPLETED"
    stop_requested = False
    for source in sources:
        sources_read += 1
        for line in _lignes(source):
            lines_read += 1
            if budget_s and lines_read % 10_000 == 0 and time.monotonic() - started >= budget_s:
                stopped_reason = "TIME_BUDGET_REACHED"
                stop_requested = True
                break
            if not line or '"venue"' not in line:
                continue
            try:
                quote = json.loads(line)
            except ValueError:
                continue
            venue = quote.get("venue")
            coin = quote.get("coin")
            if venue not in ("HL", "BIN") or coin not in target_coins:
                continue
            ts = quote.get("ts_wall_ms")
            bid = quote.get("bid")
            ask = quote.get("ask")
            if ts is None or not bid or not ask or ask <= bid:
                continue
            bucket = int(float(ts) // ds_ms)
            key = (coin, venue)
            if last_bucket.get(key) == bucket:
                continue
            last_bucket[key] = bucket
            series[coin].append((float(ts), venue, float(bid), float(ask)))
        if stop_requested or (budget_s and time.monotonic() - started >= budget_s):
            stopped_reason = "TIME_BUDGET_REACHED"
            break
    series["_meta"] = {
        "lignes_lues": lines_read,
        "sources_decouvertes": len(sources),
        "sources_lues": sources_read,
        "secondes": round(time.monotonic() - started, 3),
        "stopped_reason": stopped_reason,
        "current_only": bool(current_only),
    }
    return series


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Two-leg cross-venue paper replay (read-only).")
    parser.add_argument("--root", default=str(RACINE))
    parser.add_argument("--ds-ms", type=float, default=1000.0)
    parser.add_argument("--budget-s", type=float, default=0.0)
    parser.add_argument("--current-only", action="store_true")
    parser.add_argument("--latence-ms", type=float, default=LATENCE_MS)
    parser.add_argument("--sortie", default=str(RACINE / "runtime" / "research" / "dislocation_final_verdict.json"))
    args = parser.parse_args(argv)
    root = Path(args.root)
    series = collecter_series(
        root, ds_ms=args.ds_ms, budget_s=max(0.0, args.budget_s), current_only=args.current_only,
    )
    meta = series.pop("_meta", {})
    depth_by_coin, depth_meta = collecter_profondeur(root)
    quotes_by_coin = {coin: len(values) for coin, values in series.items() if values}
    trades = backtester(
        series,
        latence_ms=max(0.0, args.latence_ms),
        depth_by_coin=depth_by_coin,
    )
    realistic = juger(trades)
    conservative = juger(
        backtester(
            series,
            fees_ar_bps=19.0,
            latence_ms=max(0.0, args.latence_ms),
            depth_by_coin=depth_by_coin,
        )
    )
    output = {
        "schema_version": "hypersmart.cross_venue_campaign.v2",
        "meta": meta,
        "depth_meta": depth_meta,
        "quotes_par_coin": quotes_by_coin,
        "n_coins_actifs": len(quotes_by_coin),
        "params": {
            "seuil_entree_bps": SEUIL_ENTREE_BPS,
            "seuil_sortie_bps": SEUIL_SORTIE_BPS,
            "horizon_max_s": HORIZON_MAX_S,
            "latence_ms": max(0.0, args.latence_ms),
            "fees_ar_bps": FEES_AR_BPS,
            "notional_usd": NOTIONAL_USD,
        },
        "verdict_realiste_16bps": realistic,
        "verdict_conservateur_19bps": conservative,
        "trade_ids": [trade["trade_id"] for trade in trades[:100]],
        "trades": trades[:100],
        "capacite_note": (
            "taille_min_usd observee aux quatre cotes; slippage incremental=0 "
            "uniquement si capacite fraiche suffisante a l'entree et a la sortie"
        ),
        "paper_read_only": True,
        "real_execution": False,
    }
    target = Path(args.sortie)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
