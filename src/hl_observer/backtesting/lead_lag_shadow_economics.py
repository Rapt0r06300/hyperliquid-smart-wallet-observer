"""Executable economics and backtest engine for Lead-Lag shadow.

This is a structural extraction from lead_lag_shadow. Public behaviour,
economic equations, executable-capacity rules and walk-forward semantics remain
unchanged. The freeze implementation deliberately remains in lead_lag_shadow.
"""
from __future__ import annotations

import hashlib
import math
import statistics as st
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hl_observer.backtesting.anti_overfit_gate import evaluer as evaluer_dsr
from hl_observer.backtesting.anti_overfit_gate import sharpe
from hl_observer.backtesting.quant_methods import block_bootstrap
from hl_observer.backtesting.robustesse_selection import pbo_cscv

# Circularity is intentional and safe: lead_lag_shadow imports this helper only
# after all primitives below have already been defined.
from hl_observer.backtesting import lead_lag_shadow as _base

CAMPAIGN_HORIZON_MS = _base.CAMPAIGN_HORIZON_MS
CAMPAIGN_NOTIONAL_USD = _base.CAMPAIGN_NOTIONAL_USD
CAMPAIGN_MAX_REFERENCE_LAG_MS = _base.CAMPAIGN_MAX_REFERENCE_LAG_MS
CAMPAIGN_MAX_EXIT_LAG_MS = _base.CAMPAIGN_MAX_EXIT_LAG_MS
CAMPAIGN_EXECUTION_MODEL = _base.CAMPAIGN_EXECUTION_MODEL
SEUIL_CHOC_BPS = _base.SEUIL_CHOC_BPS
FRAIS_SLIPPAGE_BPS = _base.FRAIS_SLIPPAGE_BPS
HORIZONS_MS = _base.HORIZONS_MS
MIN_CHOCS = _base.MIN_CHOCS
N_PERIODES = _base.N_PERIODES
DEFAULT_HISTORY_SOURCES = _base.DEFAULT_HISTORY_SOURCES

charger_tape = _base.charger_tape
distribution_intervalles = _base.distribution_intervalles
detecter_chocs = _base.detecter_chocs
_hl_a = _base._hl_a
_hl_apres = _base._hl_apres
_top_capacity_usd = _base._top_capacity_usd


def episodes_par_horizon(
    hl: list,
    chocs: list,
    *,
    frais_slippage_bps: float,
    horizons_ms,
    coin: str = "",
    notional_usd: float = 25.0,
    max_reference_lag_ms: float = CAMPAIGN_MAX_REFERENCE_LAG_MS,
    max_exit_lag_ms: float = CAMPAIGN_MAX_EXIT_LAG_MS,
) -> dict[float, list[dict[str, Any]]]:
    """Build causal closed paper episodes from marketable HL quotes.

    Quotes without top sizes remain valid for directional research, but they
    are explicitly non-liquidatable and cannot certify an economic result.
    """

    out: dict[float, list[dict[str, Any]]] = {h: [] for h in horizons_ms}
    if not hl:
        return out
    times = [event[0] for event in hl]
    requested = max(0.0, float(notional_usd))
    for t0, direction in chocs:
        entry = _hl_apres(hl, t0, timestamps=times)
        if entry is None:
            continue
        reference = _hl_a(hl, t0)
        reference_observed_before_signal = reference is not None
        reference_age_ms = (
            (t0 - int(reference[0])) / 1e6
            if reference_observed_before_signal
            else None
        )
        if reference is None:
            # Keep a directional diagnostic row, but never certify it as
            # liquidatable economic evidence without a pre-signal mark.
            reference = entry
        entry_price = entry[3] if direction > 0 else entry[2]
        entry_side = "BUY" if direction > 0 else "SELL"
        exit_side = "SELL" if direction > 0 else "BUY"
        if entry_price <= 0:
            continue
        entry_capacity = _top_capacity_usd(entry, side=entry_side)
        for horizon in horizons_ms:
            # A quote older than the tested alpha horizon cannot establish an
            # executable lead-lag episode.  The configured limits remain hard
            # upper bounds, while the horizon supplies the causal upper bound.
            effective_reference_lag_ms = min(
                max(0.0, float(max_reference_lag_ms)),
                max(0.0, float(horizon)),
            )
            effective_exit_lag_ms = min(
                max(0.0, float(max_exit_lag_ms)),
                max(0.0, float(horizon)),
            )
            reference_fresh = bool(
                reference_observed_before_signal
                and reference_age_ms is not None
                and 0.0 <= reference_age_ms <= effective_reference_lag_ms
            )
            target_ns = t0 + int(float(horizon) * 1e6)
            if entry[0] > target_ns:
                continue
            exit_quote = _hl_apres(hl, target_ns, timestamps=times)
            if exit_quote is None or exit_quote[0] <= entry[0]:
                continue
            exit_observation_lag_ms = (exit_quote[0] - target_ns) / 1e6
            exit_quote_fresh = bool(
                0.0 <= exit_observation_lag_ms <= effective_exit_lag_ms
            )
            exit_price = exit_quote[2] if direction > 0 else exit_quote[3]
            if exit_price <= 0:
                continue
            exit_capacity = _top_capacity_usd(exit_quote, side=exit_side)
            capacity = (
                min(entry_capacity, exit_capacity)
                if entry_capacity is not None and exit_capacity is not None
                else None
            )
            liquidatable = (
                reference_fresh
                and exit_quote_fresh
                and capacity is not None
                and requested > 0
                and capacity >= requested
            )
            reference_mid = float(reference[1])
            entry_mid = float(entry[1])
            exit_mid = float(exit_quote[1])
            quantity = requested / float(entry_price) if requested > 0 else 0.0
            gross_from_reference = quantity * direction * (exit_mid - reference_mid)
            signed_latency = quantity * direction * (entry_mid - reference_mid)
            latency_cost = max(0.0, signed_latency)
            latency_benefit = max(0.0, -signed_latency)
            gross_pnl = gross_from_reference + latency_benefit
            delayed_mid_pnl = quantity * direction * (exit_mid - entry_mid)
            executable_before_fees = quantity * direction * (exit_price - entry_price)
            spread_cost = delayed_mid_pnl - executable_before_fees
            if spread_cost < -1e-8:
                continue
            spread_cost = max(0.0, spread_cost)
            per_side_fee_bps = max(0.0, float(frais_slippage_bps)) / 2.0
            fees = (
                abs(quantity * float(entry_price)) + abs(quantity * float(exit_price))
            ) * per_side_fee_bps / 10_000.0
            slippage_cost = 0.0
            net_pnl = gross_pnl - spread_cost - fees - slippage_cost - latency_cost
            if not math.isclose(net_pnl, executable_before_fees - fees, abs_tol=1e-8):
                continue
            net_bps = net_pnl / requested * 1e4 if requested > 0 else 0.0
            identity = "|".join(
                (
                    str(coin).upper(),
                    str(t0),
                    f"{float(horizon):g}",
                    f"{float(direction):g}",
                    str(entry[0]),
                    str(exit_quote[0]),
                )
            )
            out[horizon].append(
                {
                    "episode_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                    "trade_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                    "coin": str(coin).upper() or None,
                    "direction": "LONG" if direction > 0 else "SHORT",
                    "signal_ts_ns": int(t0),
                    "entry_ts_ns": int(entry[0]),
                    "exit_ts_ns": int(exit_quote[0]),
                    "horizon_ms": float(horizon),
                    "entry_latency_ms": round((entry[0] - t0) / 1e6, 6),
                    "exit_observation_lag_ms": round(exit_observation_lag_ms, 6),
                    "entry_price": float(entry_price),
                    "exit_price": float(exit_price),
                    "reference_mid": reference_mid,
                    "reference_age_ms": (
                        round(reference_age_ms, 6)
                        if reference_age_ms is not None
                        else None
                    ),
                    "configured_max_reference_lag_ms": float(max_reference_lag_ms),
                    "max_reference_lag_ms": effective_reference_lag_ms,
                    "reference_status": (
                        "OBSERVED_AT_OR_BEFORE_SIGNAL"
                        if reference_fresh
                        else "STALE_PRE_SIGNAL_QUOTE"
                        if reference_observed_before_signal
                        else "MISSING_PRE_SIGNAL_QUOTE"
                    ),
                    "exit_status": (
                        "OBSERVED_AT_OR_AFTER_TARGET"
                        if exit_quote_fresh
                        else "STALE_EXIT_QUOTE"
                    ),
                    "configured_max_exit_lag_ms": float(max_exit_lag_ms),
                    "max_exit_lag_ms": effective_exit_lag_ms,
                    "entry_mid": entry_mid,
                    "exit_mid": exit_mid,
                    "quantity": quantity,
                    "entry_side": entry_side,
                    "exit_side": exit_side,
                    "configured_round_trip_cost_bps": float(frais_slippage_bps),
                    "net_bps": float(net_bps),
                    "gross_pnl_usd": gross_pnl,
                    "fees_usd": fees,
                    "spread_cost_usd": spread_cost,
                    "slippage_cost_usd": slippage_cost,
                    "latency_cost_usd": latency_cost,
                    "latency_signed_usd": signed_latency,
                    "latency_benefit_in_gross_usd": latency_benefit,
                    "latency_cost_method": (
                        "adverse_only;favourable_component_in_gross;exact_reconciliation"
                    ),
                    "net_pnl_usd": net_pnl,
                    "requested_notional_usd": requested,
                    "top_capacity_usd": capacity,
                    "liquidatable_net": liquidatable,
                    "closed": True,
                    "opened": True,
                    "economic_reconciliation_ok": True,
                    "real_execution": False,
                    "paper_read_only": True,
                }
            )
    return out

def summarize_executable_episodes(
    episodes: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize only closed, sized, economically reconciled paper episodes."""

    all_rows = list(episodes)
    rows = [
        row
        for row in all_rows
        if row.get("liquidatable_net") is True
        and row.get("closed") is True
        and row.get("economic_reconciliation_ok") is True
    ]
    ids = [str(row.get("trade_id") or "") for row in rows]
    duplicate_ids = len(ids) - len(set(ids))
    gross = sum(float(row["gross_pnl_usd"]) for row in rows)
    fees = sum(float(row["fees_usd"]) for row in rows)
    spread = sum(float(row["spread_cost_usd"]) for row in rows)
    slippage = sum(float(row["slippage_cost_usd"]) for row in rows)
    latency = sum(float(row["latency_cost_usd"]) for row in rows)
    net = sum(float(row["net_pnl_usd"]) for row in rows)
    equity = peak = max_drawdown = gains = losses = 0.0
    wins = 0
    for row in sorted(rows, key=lambda value: int(value["exit_ts_ns"])):
        pnl = float(row["net_pnl_usd"])
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if pnl > 0:
            wins += 1
            gains += pnl
        elif pnl < 0:
            losses -= pnl
    reconciliation_ok = math.isclose(
        gross - fees - spread - slippage - latency,
        net,
        abs_tol=1e-6,
    )
    return {
        "positions_ouvertes": len(rows),
        "positions_fermees": len(rows),
        "observations_total": len(all_rows),
        "observations_non_liquidables": len(all_rows) - len(rows),
        "gross_pnl_usd": round(gross, 8),
        "fees_usd": round(fees, 8),
        "spread_cost_usd": round(spread, 8),
        "slippage_cost_usd": round(slippage, 8),
        "latency_cost_usd": round(latency, 8),
        "net_pnl_usd": round(net, 8),
        "roi_pct": round(net / 1000.0 * 100.0, 8),
        "max_drawdown_usd": round(max_drawdown, 8),
        "hit_rate": round(wins / len(rows), 8) if rows else 0.0,
        "profit_factor": round(gains / losses, 8) if losses > 0 else None,
        "LIQUIDATABLE_NET": bool(rows) and reconciliation_ok,
        "duplicate_trade_ids": duplicate_ids,
        "trade_ids_count": len(set(ids)),
        "trade_ids_sha256": hashlib.sha256(
            "\n".join(sorted(set(ids))).encode("utf-8")
        ).hexdigest(),
        "economic_reconciliation_ok": reconciliation_ok,
    }

def _placebo_direction(coin: str, signal_ts_ns: int) -> float:
    digest = hashlib.sha256(f"{coin}|{signal_ts_ns}|placebo-v1".encode("utf-8")).digest()
    return 1.0 if digest[0] & 1 else -1.0

def _temporal_bounds(signal_times: list[int], *, purge_ns: int) -> dict[str, int | None]:
    ordered = sorted(set(int(value) for value in signal_times))
    if len(ordered) < 3:
        return {
            "train_end_ns": None,
            "validation_start_ns": None,
            "validation_end_ns": None,
            "oos_start_ns": None,
            "purge_ns": int(purge_ns),
        }
    train_index = min(len(ordered) - 2, max(0, int(len(ordered) * 0.60) - 1))
    validation_index = min(
        len(ordered) - 1,
        max(train_index + 1, int(len(ordered) * 0.80) - 1),
    )
    train_end = ordered[train_index]
    validation_end = ordered[validation_index]
    return {
        "train_end_ns": train_end,
        "validation_start_ns": train_end + int(purge_ns),
        "validation_end_ns": validation_end,
        "oos_start_ns": validation_end + int(purge_ns),
        "purge_ns": int(purge_ns),
    }

def executable_campaign_evidence(
    tape: Mapping[str, Mapping[str, list]],
    *,
    frozen_at_ms: int,
    horizon_ms: float = CAMPAIGN_HORIZON_MS,
    frais_slippage_bps: float = FRAIS_SLIPPAGE_BPS,
    seuil_choc_bps: float = SEUIL_CHOC_BPS,
    notional_usd: float = CAMPAIGN_NOTIONAL_USD,
    max_reference_lag_ms: float = CAMPAIGN_MAX_REFERENCE_LAG_MS,
    max_exit_lag_ms: float = CAMPAIGN_MAX_EXIT_LAG_MS,
) -> dict[str, Any]:
    """Build the fixed-horizon, purged, post-freeze Lead-Lag paper ledger."""

    frozen_at_ns = int(frozen_at_ms) * 1_000_000
    horizon_ns = int(float(horizon_ms) * 1_000_000.0)
    candidates: list[dict[str, Any]] = []
    placebos: list[dict[str, Any]] = []
    for coin in sorted(tape):
        events = tape[coin]
        hl = list(events.get("HL") or [])
        shocks = detecter_chocs(
            list(events.get("TRADE") or []),
            seuil_bps=float(seuil_choc_bps),
        )
        if len(hl) < 3 or not shocks:
            continue
        candidates.extend(
            episodes_par_horizon(
                hl,
                shocks,
                frais_slippage_bps=float(frais_slippage_bps),
                horizons_ms=(float(horizon_ms),),
                coin=coin,
                notional_usd=float(notional_usd),
                max_reference_lag_ms=float(max_reference_lag_ms),
                max_exit_lag_ms=float(max_exit_lag_ms),
            )[float(horizon_ms)]
        )
        placebo_shocks = [
            (timestamp, _placebo_direction(coin, timestamp))
            for timestamp, _direction in shocks
        ]
        placebos.extend(
            episodes_par_horizon(
                hl,
                placebo_shocks,
                frais_slippage_bps=float(frais_slippage_bps),
                horizons_ms=(float(horizon_ms),),
                coin=coin,
                notional_usd=float(notional_usd),
                max_reference_lag_ms=float(max_reference_lag_ms),
                max_exit_lag_ms=float(max_exit_lag_ms),
            )[float(horizon_ms)]
        )

    historical_times = [
        int(row["signal_ts_ns"])
        for row in candidates
        if int(row["exit_ts_ns"]) <= frozen_at_ns
    ]
    bounds = _temporal_bounds(historical_times, purge_ns=horizon_ns)

    def segment(row: Mapping[str, Any]) -> str | None:
        signal = int(row["signal_ts_ns"])
        exit_ts = int(row["exit_ts_ns"])
        if signal > frozen_at_ns:
            return "forward"
        train_end = bounds["train_end_ns"]
        validation_start = bounds["validation_start_ns"]
        validation_end = bounds["validation_end_ns"]
        oos_start = bounds["oos_start_ns"]
        if train_end is None:
            return None
        if signal <= int(train_end) and exit_ts <= int(train_end):
            return "train"
        if (
            validation_start is not None
            and validation_end is not None
            and signal >= int(validation_start)
            and exit_ts <= int(validation_end)
        ):
            return "validation"
        if oos_start is not None and signal >= int(oos_start) and exit_ts <= frozen_at_ns:
            return "oos"
        return None

    segmented = {name: [] for name in ("train", "validation", "oos", "forward")}
    placebo_segmented = {name: [] for name in segmented}
    for row in candidates:
        name = segment(row)
        if name is not None:
            row["walk_forward_segment"] = name
            segmented[name].append(row)
    for row in placebos:
        name = segment(row)
        if name is not None:
            row["walk_forward_segment"] = name
            placebo_segmented[name].append(row)

    summaries = {
        name: summarize_executable_episodes(rows)
        for name, rows in segmented.items()
    }
    placebo_summaries = {
        name: summarize_executable_episodes(rows)
        for name, rows in placebo_segmented.items()
    }
    combined_rows = [row for rows in segmented.values() for row in rows]
    combined = summarize_executable_episodes(combined_rows)
    oos = summaries["oos"]
    forward = summaries["forward"]
    placebo_oos = placebo_summaries["oos"]
    return {
        "schema_version": "hypersmart.lead_lag_executable_campaign.v1",
        "execution_model": CAMPAIGN_EXECUTION_MODEL,
        "params": {
            "horizon_ms": float(horizon_ms),
            "seuil_choc_bps": float(seuil_choc_bps),
            "round_trip_fee_bps": float(frais_slippage_bps),
            "notional_usd": float(notional_usd),
            "max_reference_lag_ms": float(max_reference_lag_ms),
            "max_exit_lag_ms": float(max_exit_lag_ms),
            "effective_max_reference_lag_ms": min(
                float(max_reference_lag_ms), float(horizon_ms)
            ),
            "effective_max_exit_lag_ms": min(
                float(max_exit_lag_ms), float(horizon_ms)
            ),
            "freshness_cap_policy": "min(configured_lag_ms,economic_horizon_ms)",
        },
        "walk_forward_bounds": bounds,
        "summary": combined,
        "segment_summaries": summaries,
        "placebo_summaries": placebo_summaries,
        "temporal_evidence": {
            "oos": (
                {
                    **{
                        key: oos.get(key)
                        for key in (
                            "gross_pnl_usd", "fees_usd", "spread_cost_usd",
                            "slippage_cost_usd", "latency_cost_usd", "net_pnl_usd",
                            "trade_ids_count", "trade_ids_sha256", "duplicate_trade_ids",
                        )
                    },
                    "sample_count": oos["positions_fermees"],
                    "liquidatable_net": oos.get("LIQUIDATABLE_NET") is True,
                    "no_lookahead": True,
                }
                if oos["positions_fermees"] > 0
                else None
            ),
            "forward": (
                {
                    **{
                        key: forward.get(key)
                        for key in (
                            "gross_pnl_usd", "fees_usd", "spread_cost_usd",
                            "slippage_cost_usd", "latency_cost_usd", "net_pnl_usd",
                            "trade_ids_count", "trade_ids_sha256", "duplicate_trade_ids",
                        )
                    },
                    "sample_count": forward["positions_fermees"],
                    "liquidatable_net": forward.get("LIQUIDATABLE_NET") is True,
                    "post_freeze": True,
                }
                if forward["positions_fermees"] > 0
                else None
            ),
            "placebos": {
                "beaten": bool(
                    oos["positions_fermees"] > 0
                    and placebo_oos["positions_fermees"] > 0
                    and float(oos["net_pnl_usd"]) > float(placebo_oos["net_pnl_usd"])
                ),
                "candidate_oos_net_usd": oos["net_pnl_usd"],
                "placebo_oos_net_usd": placebo_oos["net_pnl_usd"],
                "candidate_sample_count": oos["positions_fermees"],
                "placebo_sample_count": placebo_oos["positions_fermees"],
            },
        },
        "diagnostics": {
            "candidate_observations": len(candidates),
            "liquidatable_observations": sum(
                1 for row in candidates if row.get("liquidatable_net") is True
            ),
            "missing_top_sizes": sum(
                1 for row in candidates if row.get("top_capacity_usd") is None
            ),
            "stale_pre_signal_quotes": sum(
                1
                for row in candidates
                if row.get("reference_status") == "STALE_PRE_SIGNAL_QUOTE"
            ),
            "stale_exit_quotes": sum(
                1 for row in candidates if row.get("exit_status") == "STALE_EXIT_QUOTE"
            ),
            "purged_or_unassigned": len(candidates) - len(combined_rows),
        },
        "trades": combined_rows,
        "paper_read_only": True,
        "real_execution": False,
    }


def calibrate_freeze_readiness(
    tape: Mapping[str, Mapping[str, list]],
    *,
    horizon_ms: float = CAMPAIGN_HORIZON_MS,
    frais_slippage_bps: float = FRAIS_SLIPPAGE_BPS,
    seuil_choc_bps: float = SEUIL_CHOC_BPS,
    notional_usd: float = CAMPAIGN_NOTIONAL_USD,
    min_liquidatable_observations: int = MIN_CHOCS,
    max_reference_lag_ms: float = CAMPAIGN_MAX_REFERENCE_LAG_MS,
    max_exit_lag_ms: float = CAMPAIGN_MAX_EXIT_LAG_MS,
) -> dict[str, Any]:
    """Check structural walk-forward readiness without selecting on PnL.

    A physical freeze must never be created against an empty or unsegmentable
    tape.  This preflight deliberately inspects only timestamps, executable
    sizing and segment counts.  It does not read segment PnL, hit rate or
    profit factor and therefore cannot cherry-pick a favourable freeze.
    """

    observed_timestamps = [
        int(row[0])
        for streams in tape.values()
        for name in ("HL", "TRADE")
        for row in (streams.get(name) or [])
        if isinstance(row, (list, tuple)) and row
    ]
    if not observed_timestamps:
        return {
            "status": "INSUFFICIENT_HISTORY_NO_OBSERVATION",
            "selection_eligible": False,
            "provisional_frozen_at_ms": None,
            "segment_counts": {name: 0 for name in ("train", "validation", "oos")},
            "liquidatable_observations": 0,
            "minimum_liquidatable_observations": int(min_liquidatable_observations),
            "selection_basis": "STRUCTURE_ONLY_NO_PNL",
        }

    provisional_frozen_at_ms = max(observed_timestamps) // 1_000_000 + 1
    evidence = executable_campaign_evidence(
        tape,
        frozen_at_ms=provisional_frozen_at_ms,
        horizon_ms=float(horizon_ms),
        frais_slippage_bps=float(frais_slippage_bps),
        seuil_choc_bps=float(seuil_choc_bps),
        notional_usd=float(notional_usd),
        max_reference_lag_ms=float(max_reference_lag_ms),
        max_exit_lag_ms=float(max_exit_lag_ms),
    )
    summaries = evidence.get("segment_summaries") or {}
    segment_counts = {
        name: int((summaries.get(name) or {}).get("positions_fermees") or 0)
        for name in ("train", "validation", "oos")
    }
    liquidatable = int(
        (evidence.get("diagnostics") or {}).get("liquidatable_observations") or 0
    )
    eligible = bool(
        liquidatable >= max(1, int(min_liquidatable_observations))
        and all(segment_counts[name] > 0 for name in segment_counts)
    )
    return {
        "status": "ELIGIBLE_TO_FREEZE" if eligible else "INSUFFICIENT_SEGMENTABLE_HISTORY",
        "selection_eligible": eligible,
        "provisional_frozen_at_ms": int(provisional_frozen_at_ms),
        "segment_counts": segment_counts,
        "liquidatable_observations": liquidatable,
        "candidate_observations": int(
            (evidence.get("diagnostics") or {}).get("candidate_observations") or 0
        ),
        "minimum_liquidatable_observations": int(min_liquidatable_observations),
        "walk_forward_bounds": evidence.get("walk_forward_bounds"),
        "selection_basis": "STRUCTURE_ONLY_NO_PNL",
        "pnl_fields_read_for_selection": [],
    }

def net_par_horizon(hl: list, chocs: list, *, frais_slippage_bps: float,
                    horizons_ms) -> dict[float, list[tuple[float, float | None]]]:
    """Project causal episodes as ``(net_bps, measured_top_capacity_usd)``."""

    episodes = episodes_par_horizon(
        hl,
        chocs,
        frais_slippage_bps=frais_slippage_bps,
        horizons_ms=horizons_ms,
    )
    return {
        horizon: [(row["net_bps"], row["top_capacity_usd"]) for row in rows]
        for horizon, rows in episodes.items()
    }

def _metriques(nets: list[float], *, n_periodes: int) -> dict[str, Any]:
    """Espérance, drawdown du cumul, et stabilité PAR PÉRIODE (pas le winrate)."""
    esper = st.mean(nets)
    cum, pic, dd = 0.0, 0.0, 0.0
    for x in nets:
        cum += x
        pic = max(pic, cum)
        dd = min(dd, cum - pic)
    taille = max(1, len(nets) // n_periodes)
    periodes = [nets[i:i + taille] for i in range(0, len(nets), taille)]
    moys = [st.mean(p) for p in periodes if p]
    bootstrap_totals = block_bootstrap(
        nets,
        block=max(1, int(math.sqrt(len(nets)))),
        n=500,
        seed=20260729,
    )
    bootstrap_means = sorted(total / len(nets) for total in bootstrap_totals)
    lower_index = max(0, int(len(bootstrap_means) * 0.025) - 1)
    upper_index = min(len(bootstrap_means) - 1, int(len(bootstrap_means) * 0.975))
    bootstrap_ci = (
        [round(bootstrap_means[lower_index], 3), round(bootstrap_means[upper_index], 3)]
        if bootstrap_means
        else [None, None]
    )
    return {"esperance_nette_bps": round(esper, 3), "n": len(nets),
            "drawdown_cumule_bps": round(dd, 2),
            "periodes_positives": (
                f"{sum(1 for value in moys if value > 0)}/{len(moys)}"
            ),
            "moyennes_par_periode_bps": [round(value, 3) for value in moys],
            "bootstrap_mean_ci95_bps": bootstrap_ci,
            "stable": bool(moys) and all(m > 0 for m in moys)}

def backtest(root: str | Path = ".", *, seuil_choc_bps: float = SEUIL_CHOC_BPS,
             frais_slippage_bps: float = FRAIS_SLIPPAGE_BPS, horizons_ms=HORIZONS_MS,
             coins_controle: tuple = (), min_chocs: int = MIN_CHOCS,
             include_history: bool = False,
             max_history_sources: int = DEFAULT_HISTORY_SOURCES,
             sources: list[Path] | None = None,
             economic_frozen_at_ms: int | None = None,
             economic_horizon_ms: float = CAMPAIGN_HORIZON_MS,
             economic_notional_usd: float = CAMPAIGN_NOTIONAL_USD) -> dict[str, Any]:
    """Verdict lead-lag NET par horizon (gaté par l'observable), par coin, test vs contrôle, avec
    espérance/capacité/drawdown/stabilité. NEED_MORE_DATA tant que trop peu de chocs."""
    tape, source_meta = charger_tape(
        root,
        include_history=include_history,
        max_history_sources=max_history_sources,
        sources=sources,
        return_meta=True,
    )
    if not tape:
        return {"strategie": "lead_lag_shadow", "statut": "NEED_MORE_DATA", "detail": "tape vide",
                "source_meta": source_meta}
    controle = {c.upper() for c in coins_controle}
    # 1) cadence HL PAR COIN (jamais poolée : l'interleaving de N coins donne un p50 illusoire ~0 ms
    #    et ferait croire que 50/100 ms sont observables alors qu'HL n'emet ~qu'aux 100 ms PAR coin).
    p50s = [d["p50_ms"] for ev in tape.values() if len(ev["HL"]) >= 5
            and (d := distribution_intervalles(ev["HL"]))["p50_ms"]]
    med_p50 = st.median(p50s) if p50s else None
    dist = {"p50_ms_par_coin_median": round(med_p50, 2) if med_p50 else None, "n_coins_mesures": len(p50s)}
    horizons = [h for h in horizons_ms if med_p50 and h >= 2.0 * med_p50]
    if not horizons:
        return {"strategie": "lead_lag_shadow", "statut": "NEED_MORE_DATA",
                "intervalles_hl": dist, "detail": "aucun horizon observable (HL trop lent / peu de data)",
                "source_meta": source_meta}
    # 2) chocs sur trades -> net par horizon, séparé test/contrôle
    import random
    test: dict[float, list] = {h: [] for h in horizons}
    ctrl: dict[float, list] = {h: [] for h in horizons}
    placebo: dict[float, list] = {h: [] for h in horizons}     # directions MÉLANGÉES -> doit donner ~0
    cap: list[float] = []
    test_event_times: list[int] = []
    for coin, ev in tape.items():
        chocs = detecter_chocs(ev["TRADE"], seuil_bps=seuil_choc_bps)
        if not chocs or len(ev["HL"]) < 3:
            continue
        nets = net_par_horizon(ev["HL"], chocs, frais_slippage_bps=frais_slippage_bps, horizons_ms=horizons)
        cible = ctrl if coin in controle else test
        for h in horizons:
            cible[h].extend(x[0] for x in nets[h])
        if coin not in controle:
            test_event_times.extend(t0 for t0, _direction in chocs)
            for h in horizons:
                cap.extend(x[1] for x in nets[h] if x[1] is not None)
            rng = random.Random(20260723)                      # placebo REPRODUCTIBLE : mêmes t0, sens aléatoire
            faux = [(t0, 1.0 if rng.random() > 0.5 else -1.0) for t0, _ in chocs]
            netpl = net_par_horizon(ev["HL"], faux, frais_slippage_bps=frais_slippage_bps, horizons_ms=horizons)
            for h in horizons:
                placebo[h].extend(x[0] for x in netpl[h])
    n_test = max((len(v) for v in test.values()), default=0)
    if n_test < min_chocs:
        return {"strategie": "lead_lag_shadow", "statut": "NEED_MORE_DATA", "chocs_test": n_test,
                "cible": min_chocs, "intervalles_hl": dist, "horizons_observables": horizons,
                "source_meta": source_meta}
    par_h = {h: _metriques(v, n_periodes=N_PERIODES) for h, v in test.items() if v}
    ctrl_h = {h: round(st.mean(v), 3) for h, v in ctrl.items() if v}
    plac_h = {h: round(st.mean(v), 3) for h, v in placebo.items() if v}
    trial_sharpes = [sharpe(values) for values in test.values() if len(values) >= 2]
    dsr_h = {
        h: evaluer_dsr(
            values,
            n_essais=max(1, len(horizons_ms)),
            trial_sharpes=trial_sharpes,
        ).as_dict()
        for h, values in test.items()
        if values
    }
    pbo_rows = [
        metrics["moyennes_par_periode_bps"]
        for metrics in par_h.values()
        if len(metrics.get("moyennes_par_periode_bps") or ()) >= 4
    ]
    pbo = pbo_cscv(pbo_rows) if len(pbo_rows) >= 2 else pbo_cscv([])
    event_frequency = None
    if len(test_event_times) >= 2:
        duration_days = (max(test_event_times) - min(test_event_times)) / 1e9 / 86400.0
        if duration_days > 0:
            event_frequency = round(len(test_event_times) / duration_days, 6)
    # KEEP seulement si : espérance>0, STABLE par période, ET bat le PLACEBO (sinon = artefact d'horloge)
    gagnants = {h: r for h, r in par_h.items()
                if r["esperance_nette_bps"] > 0 and r["stable"]
                and r["esperance_nette_bps"] > plac_h.get(h, 0.0)}
    result = {"strategie": "lead_lag_shadow",
            "statut": "PROMETTEUR" if gagnants else "PAS_D_EDGE",
            "chocs_test": n_test,
            "intervalles_hl": dist, "horizons_observables": horizons,
            "capacite_mediane_usd": round(st.median(cap), 2) if cap else None,
            "capacity_status": "MEASURED_TOP_OF_BOOK" if cap else "UNMEASURABLE_NO_TOP_SIZES",
            "net_par_horizon": par_h, "controle_par_horizon": ctrl_h, "placebo_par_horizon": plac_h,
            "dsr_par_horizon": dsr_h,
            "pbo": pbo,
            "frequence_evenements_par_jour": event_frequency,
            "information_coefficient": {
                "value": None,
                "status": "UNMEASURABLE_WITH_DIRECTION_ONLY_SHOCKS",
            },
            "regimes": {
                "period_count": N_PERIODES,
                "stable_horizons_ms": [h for h, row in par_h.items() if row.get("stable")],
            },
            "source_meta": source_meta,
            "avertissement": "Choc sur trades Binance ; entrée demi-spread HL réel + frais/slippage ; "
                             "horizons GATÉS par l'observable ; stabilité par période. Contrôle > 0 = "
                             "artefact d'horloge. Sub-seconde souvent gagnée par des racers co-localisés."}
    if economic_frozen_at_ms is not None:
        result["executable_campaign"] = executable_campaign_evidence(
            tape,
            frozen_at_ms=int(economic_frozen_at_ms),
            horizon_ms=float(economic_horizon_ms),
            frais_slippage_bps=float(frais_slippage_bps),
            seuil_choc_bps=float(seuil_choc_bps),
            notional_usd=float(economic_notional_usd),
        )
    return result
