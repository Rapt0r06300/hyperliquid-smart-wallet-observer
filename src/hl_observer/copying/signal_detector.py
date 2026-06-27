from __future__ import annotations

import copy
import hashlib
import os
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): pass

from pydantic import BaseModel, Field

from hl_observer.config.settings import Settings
from hl_observer.edge.edge_remaining import compute_edge_remaining
from hl_observer.hyperliquid.schemas import EdgeRemainingInputs, SignalCandidate, SignalDecision, SignalScore
from hl_observer.risk.gates import RiskContext
from hl_observer.risk.risk_engine import RiskEngine
from hl_observer.signals.signal_scoring import score_signal
from hl_observer.simulation.live_filters import (
    DEFAULT_HARD_STALE_SIGNAL_CAP_MS,
    DEFAULT_SIMULATION_MAX_SIGNAL_AGE_MS,
    DEFAULT_SIMULATION_MIN_EDGE_BPS,
)
from hl_observer.storage.models import PositionDeltaModel, TopWallet
from hl_observer.utils.time import now_ms


class CopySourceMode(StrEnum):
    POLLING = "polling"
    WEBSOCKET_DRY_RUN = "websocket_dry_run"


class CopySignalTuning(BaseModel):
    # Les leaders Hyperliquid font typiquement 0.5–1% de mouvement.
    # 50 bps = atténuation conservatrice.
    leader_expected_move_bps: float = 50.0
    cluster_confirmation_bps: float = 0.0
    orderbook_confirmation_bps: float = 0.0
    regime_bonus_bps: float = 0.0
    taker_fee_bps: float = 4.0
    spread_cost_bps: float = 3.0
    estimated_slippage_bps: float = 5.0
    latency_decay_bps: float = 2.0
    adverse_selection_bps: float = 2.0   # réduit (was 3)
    funding_expected_cost_bps: float = 0.0
    orderbook_depth_usdc: float = 25_000.0
    # Edge net attendu = 50 - (4+3+5+2+2) = 34 bps >> min 5 bps


class CopySignalDetectionReport(BaseModel):
    mode: CopySourceMode = CopySourceMode.POLLING
    interval_seconds: int = 300
    dry_run: bool = True
    leaders_seen: int = 0
    deltas_seen: int = 0
    signals_created: int = 0
    paper_candidates: int = 0
    rejected: int = 0
    no_trade_reasons: dict[str, int] = Field(default_factory=dict)
    signals: list[SignalCandidate] = Field(default_factory=list)
    scores: list[SignalScore] = Field(default_factory=list)
    message: str = "paper/mock-USDC dry-run only; no orders created"


def detect_copy_signals_from_deltas(
    deltas: list[PositionDeltaModel],
    *,
    settings: Settings,
    followed_wallets: list[TopWallet] | None = None,
    interval_seconds: int = 300,
    source_mode: CopySourceMode = CopySourceMode.POLLING,
    tuning: CopySignalTuning | None = None,
    now_timestamp_ms: int | None = None,
) -> CopySignalDetectionReport:
    current_ms = now_timestamp_ms or now_ms()
    risk_settings = _settings_with_simulation_overrides(settings)
    followed_scores = {
        wallet.wallet_address.lower(): float(wallet.score or 0.0)
        for wallet in (followed_wallets or [])
        if wallet.status != "rejected"
    }
    allowed_wallets = set(followed_scores)
    signals: list[SignalCandidate] = []
    scores: list[SignalScore] = []
    no_trade: dict[str, int] = {}
    cfg = tuning or CopySignalTuning()

    for delta in deltas:
        wallet_address = str(delta.wallet_address).lower()
        if allowed_wallets and wallet_address not in allowed_wallets:
            _count(no_trade, "wallet_not_followed")
            continue
        signal_type = signal_type_from_delta(delta)
        if signal_type is None:
            reason = "leader_reduce_close_not_entry" if _is_reduce_or_close(delta) else "delta_not_copyable"
            _count(no_trade, reason)
            continue
        side = side_from_delta(delta)
        if side is None:
            _count(no_trade, "side_unknown")
            continue
        if delta.price is None or delta.price <= 0:
            _count(no_trade, "price_missing")
            continue
        edge = compute_edge_remaining(
            EdgeRemainingInputs(
                leader_expected_move_bps=cfg.leader_expected_move_bps,
                cluster_confirmation_bps=cfg.cluster_confirmation_bps,
                orderbook_confirmation_bps=cfg.orderbook_confirmation_bps,
                regime_bonus_bps=cfg.regime_bonus_bps,
                taker_fee_bps=cfg.taker_fee_bps,
                spread_cost_bps=cfg.spread_cost_bps,
                estimated_slippage_bps=cfg.estimated_slippage_bps,
                latency_decay_bps=cfg.latency_decay_bps,
                adverse_selection_bps=cfg.adverse_selection_bps,
                funding_expected_cost_bps=cfg.funding_expected_cost_bps,
            ),
            min_edge_required_bps=risk_settings.risk.min_edge_required_bps,
        )
        if edge.edge_remaining_bps <= 0:
            _count(no_trade, "edge_remaining_bps_non_positive")
        timestamp_ms = delta.exchange_ts or delta.detected_at_ms or current_ms
        signal = SignalCandidate(
            id=_copy_signal_id(delta),
            source_wallet=wallet_address,
            coin=delta.coin,
            side=side,
            signal_type=signal_type,
            observed_price=float(delta.price),
            timestamp_ms=timestamp_ms,
            signal_age_ms=max(0, current_ms - timestamp_ms),
            wallet_score=followed_scores.get(wallet_address, 75.0),
            edge_remaining_bps=edge.edge_remaining_bps,
            estimated_fee_bps=cfg.taker_fee_bps,
            estimated_spread_bps=cfg.spread_cost_bps,
            estimated_slippage_bps=cfg.estimated_slippage_bps,
            estimated_latency_decay_bps=cfg.latency_decay_bps,
            orderbook_depth_usdc=cfg.orderbook_depth_usdc,
            crowding_score=0.0,
            exit_plan_id=f"exit:{wallet_address}:{delta.coin}",
            decision=edge.decision,
            reject_reason="; ".join(edge.reasons) if edge.decision != SignalDecision.PAPER_CANDIDATE else None,
        )
        scored = score_signal(signal)
        risk = RiskEngine(risk_settings).evaluate(
            RiskContext(
                spread_bps=cfg.spread_cost_bps,
                estimated_slippage_bps=cfg.estimated_slippage_bps,
                orderbook_depth_usdc=cfg.orderbook_depth_usdc,
                wallet_score=signal.wallet_score,
                signal_score=scored.score,
                edge_remaining_bps=edge.edge_remaining_bps,
                signal_age_ms=signal.signal_age_ms,
            )
        )
        if not risk.allowed:
            _count(no_trade, risk.decision.value)
            signal = signal.model_copy(update={"decision": risk.decision, "reject_reason": "; ".join(risk.reasons)})
            scored = scored.model_copy(update={"decision": risk.decision, "reasons": [*scored.reasons, *risk.reasons]})
        else:
            signal = signal.model_copy(update={"decision": SignalDecision.PAPER_TRADE, "signal_score": scored.score})
        signals.append(signal)
        scores.append(scored)

    paper_candidates = sum(1 for signal in signals if signal.decision in {SignalDecision.PAPER_TRADE, SignalDecision.PAPER_CANDIDATE})
    rejected = sum(1 for signal in signals if signal.decision.value.startswith("REJECT"))
    return CopySignalDetectionReport(
        mode=source_mode,
        interval_seconds=interval_seconds,
        leaders_seen=len(followed_wallets or []),
        deltas_seen=len(deltas),
        signals_created=len(signals),
        paper_candidates=paper_candidates,
        rejected=rejected,
        no_trade_reasons=no_trade,
        signals=signals,
        scores=scores,
    )


def _settings_with_simulation_overrides(settings: Settings) -> Settings:
    """Use V9 local simulation thresholds without permitting real execution.

    Older generic risk defaults are intentionally stricter than the live paper
    simulation launcher. In V9 the copy detector is a research/paper component:
    default freshness is 15s and default net-edge threshold is 15 bps, with env
    overrides still available for experiments. This only changes local paper
    candidate creation; it does not send or authorize any external order.
    """

    configured_age_ms = _simulation_age_ms(settings)
    configured_min_edge_bps = _simulation_min_edge_bps(settings)
    if (
        configured_age_ms == settings.risk.max_signal_age_ms
        and configured_min_edge_bps == settings.risk.min_edge_required_bps
    ):
        return settings
    cloned = copy.deepcopy(settings)
    cloned.risk.max_signal_age_ms = configured_age_ms
    cloned.risk.min_edge_required_bps = configured_min_edge_bps
    return cloned


def _simulation_age_ms(settings: Settings) -> int:
    raw_value = os.environ.get("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS")
    if raw_value:
        try:
            configured_ms = int(raw_value)
        except (TypeError, ValueError):
            configured_ms = DEFAULT_SIMULATION_MAX_SIGNAL_AGE_MS
    else:
        configured_ms = max(int(settings.risk.max_signal_age_ms), DEFAULT_SIMULATION_MAX_SIGNAL_AGE_MS)
    return min(max(1_000, configured_ms), DEFAULT_HARD_STALE_SIGNAL_CAP_MS)


def _simulation_min_edge_bps(settings: Settings) -> float:
    raw_value = os.environ.get("HYPERSMART_SIMULATION_MIN_EDGE_BPS")
    if raw_value:
        try:
            return max(0.0, float(raw_value))
        except (TypeError, ValueError):
            return DEFAULT_SIMULATION_MIN_EDGE_BPS
    return min(float(settings.risk.min_edge_required_bps), DEFAULT_SIMULATION_MIN_EDGE_BPS)


def _settings_with_simulation_age_override(settings: Settings) -> Settings:
    """Backward-compatible alias for older tests/imports."""

    return _settings_with_simulation_overrides(settings)


def signal_type_from_delta(delta: PositionDeltaModel) -> str | None:
    value = _delta_value(delta)
    if value.startswith("open"):
        return "open"
    if value.startswith("add"):
        return "add"
    if value.startswith("flip"):
        return "flip"
    return None


def side_from_delta(delta: PositionDeltaModel) -> str | None:
    value = _delta_value(delta)
    if "long" in value:
        return "long"
    if "short" in value:
        return "short"
    if delta.current_size > 0:
        return "long"
    if delta.current_size < 0:
        return "short"
    return None


def _delta_value(delta: PositionDeltaModel) -> str:
    return str(delta.delta_type or delta.action or "").strip().lower()


def _is_reduce_or_close(delta: PositionDeltaModel) -> bool:
    value = _delta_value(delta)
    return value.startswith("reduce") or value.startswith("close")


def _copy_signal_id(delta: PositionDeltaModel) -> str:
    payload = f"{delta.wallet_address}:{delta.coin}:{delta.id}:{delta.delta_hash}:{delta.exchange_ts}:{delta.detected_at_ms}:{delta.delta_type}"
    return "copy:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _count(target: dict[str, int], key: str) -> None:
    target[key] = target.get(key, 0) + 1
