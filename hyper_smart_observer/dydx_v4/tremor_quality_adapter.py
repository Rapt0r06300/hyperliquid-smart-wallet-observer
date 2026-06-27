"""Adapter TremorEngine -> SignalQuality gate.

This module keeps integration small and safe: live code can call these helpers
without changing scanner, market flow, edge calculator or paper execution.
"""

from __future__ import annotations

from dataclasses import dataclass

from hyper_smart_observer.dydx_v4.signal_quality import (
    SignalQualityDecision,
    SignalQualityInput,
    evaluate_signal_quality,
)
from hyper_smart_observer.dydx_v4.tremor_engine import (
    TremorEvent,
    TremorObservation,
    evaluate_tremor,
    observation_from_cluster,
    observation_from_flow,
)


@dataclass(frozen=True)
class TremorQualityResult:
    tremor: TremorEvent
    quality: SignalQualityDecision

    @property
    def paper_eligible(self) -> bool:
        return self.tremor.is_actionable_paper_candidate and self.quality.accepted_for_paper

    def to_dict(self) -> dict:
        return {
            "tremor": self.tremor.to_log_dict(),
            "quality": self.quality.to_dict(),
            "paper_eligible": self.paper_eligible,
            "paper_only": True,
            "read_only": True,
        }


def quality_input_from_tremor(tremor: TremorEvent, *, spread_bps: float = 0.0, slippage_bps: float = 0.0) -> SignalQualityInput:
    return SignalQualityInput(
        market_id=tremor.market_id,
        side=tremor.direction,
        tremor_score=tremor.intensity_score,
        tremor_phase=tremor.timeline_phase,
        signal_age_ms=tremor.signal_age_ms,
        wallet_count=tremor.consensus_wallets,
        flow_imbalance=tremor.flow_imbalance,
        flow_volume_usdc=tremor.flow_volume_usdc,
        edge_remaining_bps=float(tremor.edge_remaining_bps or 0.0),
        market_regime=tremor.market_regime,
        data_source=tremor.source,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
    )


def evaluate_tremor_quality(obs: TremorObservation, *, spread_bps: float = 0.0, slippage_bps: float = 0.0) -> TremorQualityResult:
    tremor = evaluate_tremor(obs)
    quality = evaluate_signal_quality(
        quality_input_from_tremor(tremor, spread_bps=spread_bps, slippage_bps=slippage_bps)
    )
    return TremorQualityResult(tremor=tremor, quality=quality)


def evaluate_cluster_quality(
    *,
    market_id: str,
    direction: str,
    wallet_count: int,
    signal_age_ms: int,
    total_notional_usdc: float = 0.0,
    price_move_bps: float = 0.0,
    volume_zscore: float = 0.0,
    flow_imbalance: float = 0.0,
    flow_trade_count: int = 0,
    large_trade_usdc: float = 0.0,
    edge_remaining_bps: float | None = None,
    market_regime: str = "UNKNOWN",
    market_confidence: float = 0.0,
    source: str = "wallet_cluster",
    spread_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> TremorQualityResult:
    obs = observation_from_cluster(
        market_id=market_id,
        direction=direction,
        wallet_count=wallet_count,
        signal_age_ms=signal_age_ms,
        total_notional_usdc=total_notional_usdc,
        price_move_bps=price_move_bps,
        volume_zscore=volume_zscore,
        flow_imbalance=flow_imbalance,
        flow_trade_count=flow_trade_count,
        large_trade_usdc=large_trade_usdc,
        edge_remaining_bps=edge_remaining_bps,
        market_regime=market_regime,
        market_confidence=market_confidence,
        source=source,
    )
    return evaluate_tremor_quality(obs, spread_bps=spread_bps, slippage_bps=slippage_bps)


def evaluate_flow_quality(
    *,
    market_id: str,
    direction: str,
    flow_imbalance: float,
    flow_volume_usdc: float,
    flow_trade_count: int,
    large_trade_usdc: float = 0.0,
    price_move_bps: float = 0.0,
    volume_zscore: float = 0.0,
    signal_age_ms: int = 0,
    market_regime: str = "UNKNOWN",
    market_confidence: float = 0.0,
    edge_remaining_bps: float | None = None,
) -> TremorQualityResult:
    obs = observation_from_flow(
        market_id=market_id,
        direction=direction,
        flow_imbalance=flow_imbalance,
        flow_volume_usdc=flow_volume_usdc,
        flow_trade_count=flow_trade_count,
        large_trade_usdc=large_trade_usdc,
        price_move_bps=price_move_bps,
        volume_zscore=volume_zscore,
        signal_age_ms=signal_age_ms,
        market_regime=market_regime,
        market_confidence=market_confidence,
        edge_remaining_bps=edge_remaining_bps,
    )
    return evaluate_tremor_quality(obs)


__all__ = [
    "TremorQualityResult",
    "evaluate_cluster_quality",
    "evaluate_flow_quality",
    "evaluate_tremor_quality",
    "quality_input_from_tremor",
]
