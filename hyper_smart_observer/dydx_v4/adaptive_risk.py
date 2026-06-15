"""Adaptive paper risk engine for dYdX v4.

Goal: be careful without blocking everything. The engine returns one of:
- BLOCK: do not open paper position.
- REDUCE: position can open with reduced notional.
- ALLOW: normal paper position.
- BOOST: exceptionally strong paper setup; capped boost only.

Pure/read-only. No orders, no private keys, no network calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
try:
    from enum import StrEnum
except ImportError:  # pragma: no cover
    from enum import Enum

    class StrEnum(str, Enum):
        def __str__(self) -> str:
            return self.value


class RiskAction(StrEnum):
    BLOCK = "BLOCK"
    REDUCE = "REDUCE"
    ALLOW = "ALLOW"
    BOOST = "BOOST"


@dataclass(frozen=True)
class AdaptiveRiskProfile:
    min_quality_score: float = 58.0
    normal_quality_score: float = 72.0
    boost_quality_score: float = 88.0
    min_edge_bps: float = 3.0
    strong_edge_bps: float = 18.0
    max_signal_age_ms: int = 30_000
    soft_age_ms: int = 12_000
    max_spread_bps: float = 35.0
    max_slippage_bps: float = 14.0
    max_market_exposure_usdc: float = 220.0
    max_same_side_correlated: int = 5
    min_size_multiplier: float = 0.25
    max_size_multiplier: float = 1.25
    block_choppy: bool = True
    block_after_move: bool = True
    soft_daily_loss_usdc: float = -18.0
    hard_daily_loss_usdc: float = -45.0
    soft_consecutive_losses: int = 3
    hard_consecutive_losses: int = 6
    min_quality_after_losses: float = 70.0


@dataclass(frozen=True)
class AdaptiveRiskInput:
    market_id: str
    side: str
    quality_score: float = 0.0
    tremor_score: float = 0.0
    tremor_phase: str = "UNKNOWN"
    edge_remaining_bps: float = 0.0
    signal_age_ms: int = 0
    spread_bps: float = 0.0
    slippage_bps: float = 0.0
    market_regime: str = "UNKNOWN"
    wallet_count: int = 0
    flow_imbalance: float = 0.0
    open_positions: int = 0
    current_market_exposure_usdc: float = 0.0
    correlated_same_side_count: int = 0
    consecutive_losses: int = 0
    daily_pnl_usdc: float = 0.0
    data_source: str = "UNKNOWN"


@dataclass(frozen=True)
class AdaptiveRiskDecision:
    action: RiskAction
    size_multiplier: float
    risk_score: float
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    paper_only: bool = True
    read_only: bool = True

    @property
    def can_open(self) -> bool:
        return self.action in {RiskAction.REDUCE, RiskAction.ALLOW, RiskAction.BOOST}

    def apply_to_notional(self, base_notional: float) -> float:
        return max(0.0, base_notional * self.size_multiplier)

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "can_open": self.can_open,
            "size_multiplier": round(self.size_multiplier, 4),
            "risk_score": round(self.risk_score, 4),
            "reasons": list(self.reasons),
            "notes": list(self.notes),
            "paper_only": self.paper_only,
            "read_only": self.read_only,
        }


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def adaptive_risk_score(inp: AdaptiveRiskInput, profile: AdaptiveRiskProfile | None = None) -> float:
    p = profile or AdaptiveRiskProfile()
    score = 100.0
    score -= _clamp((p.normal_quality_score - inp.quality_score) / 30.0, 0.0, 1.0) * 22.0
    score -= _clamp((p.min_edge_bps - inp.edge_remaining_bps) / max(1.0, p.min_edge_bps), 0.0, 1.0) * 20.0
    score -= _clamp((inp.signal_age_ms - p.soft_age_ms) / max(1, p.max_signal_age_ms - p.soft_age_ms), 0.0, 1.0) * 12.0
    score -= _clamp((inp.spread_bps - p.max_spread_bps * 0.5) / max(1.0, p.max_spread_bps), 0.0, 1.0) * 10.0
    score -= _clamp((inp.slippage_bps - p.max_slippage_bps * 0.5) / max(1.0, p.max_slippage_bps), 0.0, 1.0) * 10.0
    score -= _clamp(inp.current_market_exposure_usdc / max(1.0, p.max_market_exposure_usdc), 0.0, 1.0) * 8.0
    score -= _clamp(inp.correlated_same_side_count / max(1, p.max_same_side_correlated), 0.0, 1.0) * 8.0
    score -= _clamp(inp.consecutive_losses / max(1.0, float(p.hard_consecutive_losses)), 0.0, 1.0) * 12.0
    if inp.daily_pnl_usdc < 0:
        score -= _clamp(abs(inp.daily_pnl_usdc) / max(1.0, abs(p.hard_daily_loss_usdc)), 0.0, 1.0) * 12.0
    if inp.market_regime.upper() == "CHOPPY":
        score -= 18.0
    if inp.tremor_phase == "AFTER_MOVE":
        score -= 18.0
    if inp.wallet_count >= 3 and inp.edge_remaining_bps >= p.strong_edge_bps:
        score += 6.0
    if inp.tremor_phase == "BEFORE_MOVE" and inp.quality_score >= p.normal_quality_score:
        score += 5.0
    return round(_clamp(score, 0.0, 100.0), 4)


def evaluate_adaptive_risk(inp: AdaptiveRiskInput, profile: AdaptiveRiskProfile | None = None) -> AdaptiveRiskDecision:
    p = profile or AdaptiveRiskProfile()
    reasons: list[str] = []
    notes: list[str] = []
    score = adaptive_risk_score(inp, p)

    hard_block = False
    if inp.quality_score < p.min_quality_score:
        hard_block = True
        reasons.append("QUALITY_TOO_LOW")
    if inp.edge_remaining_bps < p.min_edge_bps:
        hard_block = True
        reasons.append("EDGE_TOO_LOW")
    if inp.signal_age_ms > p.max_signal_age_ms:
        hard_block = True
        reasons.append("SIGNAL_TOO_OLD")
    if inp.spread_bps > p.max_spread_bps:
        hard_block = True
        reasons.append("SPREAD_TOO_WIDE")
    if inp.slippage_bps > p.max_slippage_bps:
        hard_block = True
        reasons.append("SLIPPAGE_TOO_HIGH")
    if p.block_choppy and inp.market_regime.upper() == "CHOPPY":
        hard_block = True
        reasons.append("CHOPPY_MARKET")
    if p.block_after_move and inp.tremor_phase == "AFTER_MOVE":
        hard_block = True
        reasons.append("AFTER_MOVE")
    if inp.current_market_exposure_usdc >= p.max_market_exposure_usdc:
        hard_block = True
        reasons.append("MARKET_EXPOSURE_LIMIT")
    if inp.correlated_same_side_count > p.max_same_side_correlated:
        hard_block = True
        reasons.append("CORRELATION_LIMIT")
    if inp.daily_pnl_usdc <= p.hard_daily_loss_usdc:
        hard_block = True
        reasons.append("DAILY_LOSS_GUARD")
    if inp.consecutive_losses >= p.hard_consecutive_losses:
        hard_block = True
        reasons.append("LOSS_STREAK_GUARD")
    if inp.consecutive_losses >= p.soft_consecutive_losses and inp.quality_score < p.min_quality_after_losses:
        hard_block = True
        reasons.append("QUALITY_TOO_LOW_AFTER_LOSSES")

    if inp.data_source not in {"REAL_INDEXER", "orderbook_real", "stream", "rest", "wallet_cluster"}:
        notes.append(f"non_primary_source={inp.data_source}")
    if inp.daily_pnl_usdc < 0:
        notes.append(f"daily_pnl={inp.daily_pnl_usdc:.4f}")
    if inp.consecutive_losses > 0:
        notes.append(f"loss_streak={inp.consecutive_losses}")

    if hard_block:
        return AdaptiveRiskDecision(RiskAction.BLOCK, 0.0, score, reasons, notes)

    if score >= p.boost_quality_score and inp.edge_remaining_bps >= p.strong_edge_bps and inp.daily_pnl_usdc >= 0:
        mult = min(p.max_size_multiplier, 1.0 + min(0.25, (score - p.boost_quality_score) / 80.0))
        return AdaptiveRiskDecision(RiskAction.BOOST, mult, score, reasons, notes + ["strong_setup_capped_boost"])

    if score >= p.normal_quality_score:
        mult = 1.0
        if inp.daily_pnl_usdc <= p.soft_daily_loss_usdc or inp.consecutive_losses >= p.soft_consecutive_losses:
            mult = 0.65
            notes.append("session_pressure_reduced_size")
        return AdaptiveRiskDecision(RiskAction.ALLOW, mult, score, reasons, notes)

    soft = _clamp((score - p.min_quality_score) / max(1.0, p.normal_quality_score - p.min_quality_score), 0.0, 1.0)
    mult = p.min_size_multiplier + (0.75 - p.min_size_multiplier) * soft
    if inp.daily_pnl_usdc <= p.soft_daily_loss_usdc or inp.consecutive_losses >= p.soft_consecutive_losses:
        mult *= 0.6
        notes.append("session_pressure_reduced_size")
    return AdaptiveRiskDecision(RiskAction.REDUCE, round(mult, 4), score, ["SOFT_RISK_REDUCED_SIZE"], notes)


__all__ = [
    "AdaptiveRiskDecision",
    "AdaptiveRiskInput",
    "AdaptiveRiskProfile",
    "RiskAction",
    "adaptive_risk_score",
    "evaluate_adaptive_risk",
]
