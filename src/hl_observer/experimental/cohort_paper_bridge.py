"""Canonical paper execution bridge for the experimental copy cohorts.

The cohort selector remains responsible for deciding *which* fresh leader
event is eligible.  This module owns the economic boundary: every accepted
OPEN/ADD/REDUCE/CLOSE is delegated to :class:`PaperEngine` and its
:class:`PaperLedger`.  Legacy cohort JSON files are compatibility projections,
not an independent fill or PnL engine.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from hashlib import sha256
from typing import Any

from hl_observer.market_data.live_l2_service import snapshot_from_mapping
from hl_observer.paper_trading.exec_model import ExecModelConfig
from hl_observer.paper_trading.paper_engine import (
    PaperDecisionResult,
    PaperEngine,
    PaperEngineConfig,
    PaperPosition,
)
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.leader_delta import LeaderDelta

ECONOMIC_SOURCE = "PAPER_ENGINE_CANONICAL"


def canonical_execution_truth(
    coin: str,
    l2_payload: Mapping[str, Any] | None,
    *,
    now_ms: int,
):
    """Build strict execution truth from one real, full L2 observation."""

    snapshot = snapshot_from_mapping(
        coin,
        l2_payload,
        source="hyperliquid:copy-vault:l2",
        now_ms=now_ms,
    )
    return None if snapshot is None else snapshot.execution_truth()


def build_engine(
    cohort: Any,
    store: dict[str, Any],
    *,
    taker_fee_bps: float,
) -> PaperEngine:
    """Build and hydrate one canonical engine from recorded cohort state."""

    prior_realized = float(store.get("realise_total_usd") or 0.0)
    starting_equity = float(cohort.budget_usd) + prior_realized
    exec_model = replace(
        ExecModelConfig(),
        taker_fee_bps=max(0.0, float(taker_fee_bps)),
    )
    engine = PaperEngine(
        config=PaperEngineConfig(
            starting_cash_usdt=starting_equity,
            max_position_usdt=float(cohort.notional_usd),
            max_total_exposure_usdt=max(0.0, starting_equity),
            max_total_margin_usdt=max(0.0, starting_equity),
            max_open_positions=int(cohort.max_positions),
            leverage=1.0,
            strict_execution_truth=True,
            max_execution_book_age_ms=1_000,
            min_execution_fill_ratio=1.0,
            exec_model=exec_model,
        )
    )
    for key, payload in (store.get("ouvertes") or {}).items():
        position = position_from_projection(str(key), payload)
        engine.restore_position(
            position,
            refs={
                "economic_source": ECONOMIC_SOURCE,
                "projection_key": str(key),
                "cohort": str(cohort.nom),
            },
        )
    return engine


def position_from_projection(key: str, payload: Mapping[str, Any]) -> PaperPosition:
    """Convert a recorded compatibility projection into canonical state."""

    meta = dict(payload.get("meta") or {})
    coin = str(payload.get("coin") or "").upper()
    side = "LONG" if int(payload.get("sens") or 0) > 0 else "SHORT"
    entry = float(payload.get("prix_entree") or 0.0)
    notional = float(payload.get("notional_usd") or 0.0)
    quantity = float(payload.get("quantity") or 0.0)
    if quantity <= 0 and entry > 0:
        quantity = notional / entry
    position_id = str(
        meta.get("paper_position_id")
        or _stable_id(
            "cohort-paper-position",
            str(meta.get("vault") or ""),
            coin,
            side,
            str(meta.get("cycle_id") or key),
        )
    )
    return PaperPosition(
        position_id=position_id,
        coin=coin,
        side=side,
        quantity=quantity,
        entry_price=entry,
        notional_usdt=notional,
        opened_at_ms=int(payload.get("ts_ouverture_ms") or 1),
        source_delta_id=str(
            meta.get("source_delta_id")
            or _stable_id("restored-delta", position_id)
        ),
        leader_wallet=str(meta.get("vault") or ""),
        margin_locked_usdt=float(
            payload.get("margin_locked_usd")
            or notional
        ),
        leverage_effective=1.0,
        leg_notional_usdt=(notional,),
    )


def apply_entry(
    engine: PaperEngine,
    *,
    wallet: str,
    coin: str,
    side_sign: int,
    leader_size: float,
    observed_at_ms: int,
    leader_event_time_ms: int,
    evidence_ref: str,
    edge_remaining_bps: float | None,
    wallet_score: float | None,
    signal_score: float,
    estimated_slippage_bps: float,
    target_notional_usdt: float,
    execution_truth,
    decision_context: Mapping[str, Any] | None = None,
) -> PaperDecisionResult:
    side_size = abs(float(leader_size)) * (1.0 if side_sign > 0 else -1.0)
    action = (
        LifecycleAction.OPEN_LONG
        if side_sign > 0
        else LifecycleAction.OPEN_SHORT
    )
    entry_reasons: tuple[str, ...] = ()
    if edge_remaining_bps is None:
        entry_reasons += ("EDGE_UNMEASURABLE",)
    if wallet_score is None:
        entry_reasons += ("WALLET_SCORE_UNMEASURABLE",)
    delta = LeaderDelta(
        delta_id=_stable_id(
            "cohort-delta",
            wallet,
            coin,
            action.value,
            leader_event_time_ms,
            evidence_ref,
        ),
        wallet=str(wallet),
        coin=str(coin).upper(),
        action=action,
        previous_size=0.0,
        current_size=side_size,
        delta_size=side_size,
        observed_at_ms=int(observed_at_ms),
        leader_event_time_ms=int(leader_event_time_ms),
        source="hyperliquid:userFills:live",
        confidence=max(0.0, min(1.0, float(signal_score) / 100.0)),
        evidence_ref=str(evidence_ref),
        leader_reference_price=None,
        reason_codes=entry_reasons,
    )
    scale = min(
        1.0,
        max(
            0.1,
            float(target_notional_usdt)
            / max(engine.config.max_position_usdt, 1e-12),
        ),
    )
    return engine.apply_delta(
        delta,
        market_price=execution_truth.mid_price,
        observed_at_ms=int(observed_at_ms),
        edge_remaining_bps=(
            0.0 if edge_remaining_bps is None else float(edge_remaining_bps)
        ),
        spread_bps=execution_truth.spread_bps,
        estimated_slippage_bps=float(estimated_slippage_bps),
        top_depth_usdt=execution_truth.visible_notional(
            "BUY" if side_sign > 0 else "SELL"
        ),
        wallet_score=0.0 if wallet_score is None else float(wallet_score),
        signal_score=float(signal_score),
        marks={str(coin).upper(): execution_truth.mid_price},
        margin_scale=scale,
        decision_context={
            "strategy_id": "copy_vault_cohort",
            "economic_source": ECONOMIC_SOURCE,
            **dict(decision_context or {}),
        },
        execution_truth=execution_truth,
    )


def apply_exit(
    engine: PaperEngine,
    *,
    position_payload: Mapping[str, Any],
    fraction: float,
    observed_at_ms: int,
    leader_event_time_ms: int,
    evidence_ref: str,
    execution_truth,
    reason: str,
    decision_context: Mapping[str, Any] | None = None,
) -> PaperDecisionResult:
    restored = position_from_projection(
        str(position_payload.get("paire") or position_payload.get("coin") or ""),
        position_payload,
    )
    fraction = max(0.0, min(1.0, float(fraction)))
    previous_size = restored.quantity if restored.side == "LONG" else -restored.quantity
    current_size = previous_size * (1.0 - fraction)
    if fraction >= 0.999:
        action = (
            LifecycleAction.CLOSE_LONG
            if restored.side == "LONG"
            else LifecycleAction.CLOSE_SHORT
        )
        current_size = 0.0
    else:
        action = LifecycleAction.REDUCE
    delta = LeaderDelta(
        delta_id=_stable_id(
            "cohort-delta",
            restored.leader_wallet,
            restored.coin,
            action.value,
            leader_event_time_ms,
            evidence_ref,
        ),
        wallet=restored.leader_wallet,
        coin=restored.coin,
        action=action,
        previous_size=previous_size,
        current_size=current_size,
        delta_size=current_size - previous_size,
        observed_at_ms=int(observed_at_ms),
        leader_event_time_ms=int(leader_event_time_ms),
        source="hyperliquid:userFills:live",
        confidence=1.0,
        evidence_ref=str(evidence_ref),
        source_position_id=restored.position_id,
    )
    return engine.apply_delta(
        delta,
        market_price=execution_truth.mid_price,
        observed_at_ms=int(observed_at_ms),
        edge_remaining_bps=0.0,
        spread_bps=execution_truth.spread_bps,
        estimated_slippage_bps=0.0,
        top_depth_usdt=execution_truth.visible_notional(
            "SELL" if restored.side == "LONG" else "BUY"
        ),
        wallet_score=100.0,
        signal_score=100.0,
        marks={restored.coin: execution_truth.mid_price},
        decision_context={
            "strategy_id": "copy_vault_cohort",
            "economic_source": ECONOMIC_SOURCE,
            "paper_position_id": restored.position_id,
            "exit_reason": str(reason),
            **dict(decision_context or {}),
        },
        execution_truth=execution_truth,
    )


def available_margin_usdt(cohort: Any, store: Mapping[str, Any]) -> float:
    locked = sum(
        float(position.get("margin_locked_usd") or position.get("notional_usd") or 0.0)
        for position in (store.get("ouvertes") or {}).values()
    )
    return round(
        max(
            0.0,
            float(cohort.budget_usd)
            + float(store.get("realise_total_usd") or 0.0)
            - locked,
        ),
        8,
    )


def _stable_id(prefix: str, *parts: object) -> str:
    material = "|".join(str(part) for part in parts)
    return f"{prefix}:" + sha256(material.encode("utf-8")).hexdigest()


__all__ = [
    "ECONOMIC_SOURCE",
    "apply_entry",
    "apply_exit",
    "available_margin_usdt",
    "build_engine",
    "canonical_execution_truth",
    "position_from_projection",
]
