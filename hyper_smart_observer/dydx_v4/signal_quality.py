"""dYdX v4 paper signal quality gate.

Pure, read-only scoring layer used before paper simulation. It combines tremor
phase, intensity, market context, flow, wallet confluence, edge and data source.
It never opens orders and never mutates logs.
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


class QualityDecision(StrEnum):
    REJECT = "REJECT"
    WATCH = "WATCH"
    PAPER_ELIGIBLE = "PAPER_ELIGIBLE"


@dataclass(frozen=True)
class QualityProfile:
    min_score: float = 72.0
    min_tremor_score: float = 6.5
    min_edge_bps: float = 3.0
    max_signal_age_ms: int = 30_000
    min_wallets: int = 2
    min_flow_imbalance: float = 0.62
    min_flow_volume_usdc: float = 10_000.0
    block_after_move: bool = True
    block_choppy: bool = True
    real_sources: set[str] = field(default_factory=lambda: {"REAL_INDEXER", "orderbook_real", "stream", "rest", "wallet_cluster"})


@dataclass(frozen=True)
class SignalQualityInput:
    market_id: str
    side: str
    tremor_score: float = 0.0
    tremor_phase: str = "UNKNOWN"
    signal_age_ms: int = 0
    wallet_count: int = 0
    flow_imbalance: float = 0.0
    flow_volume_usdc: float = 0.0
    edge_remaining_bps: float = 0.0
    market_regime: str = "UNKNOWN"
    data_source: str = "UNKNOWN"
    spread_bps: float = 0.0
    slippage_bps: float = 0.0


@dataclass(frozen=True)
class SignalQualityDecision:
    decision: QualityDecision
    score: float
    reasons: list[str]
    notes: list[str]
    paper_only: bool = True
    read_only: bool = True

    @property
    def accepted_for_paper(self) -> bool:
        return self.decision == QualityDecision.PAPER_ELIGIBLE

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "score": round(self.score, 4),
            "reasons": list(self.reasons),
            "notes": list(self.notes),
            "paper_only": self.paper_only,
            "read_only": self.read_only,
        }


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def quality_score(inp: SignalQualityInput, profile: QualityProfile | None = None) -> float:
    p = profile or QualityProfile()
    score = 0.0
    score += _clamp(inp.tremor_score / 10.0, 0.0, 1.0) * 25.0
    score += _clamp(inp.edge_remaining_bps / max(1.0, p.min_edge_bps * 4.0), 0.0, 1.0) * 20.0
    score += _clamp(inp.wallet_count / max(1, p.min_wallets * 2), 0.0, 1.0) * 18.0
    score += _clamp((abs(inp.flow_imbalance) - 0.5) / 0.5, 0.0, 1.0) * 12.0
    score += _clamp(inp.flow_volume_usdc / max(1.0, p.min_flow_volume_usdc * 3.0), 0.0, 1.0) * 8.0
    score += _clamp(1.0 - inp.signal_age_ms / max(1, p.max_signal_age_ms), 0.0, 1.0) * 10.0
    if inp.tremor_phase == "BEFORE_MOVE":
        score += 5.0
    elif inp.tremor_phase == "DURING_MOVE":
        score += 2.5
    if inp.market_regime.upper() == "TRENDING":
        score += 2.0
    return round(_clamp(score, 0.0, 100.0), 4)


def evaluate_signal_quality(inp: SignalQualityInput, profile: QualityProfile | None = None) -> SignalQualityDecision:
    p = profile or QualityProfile()
    score = quality_score(inp, p)
    reasons: list[str] = []
    notes: list[str] = []

    if inp.tremor_score < p.min_tremor_score:
        reasons.append("TREMOR_SCORE_TOO_LOW")
    if inp.edge_remaining_bps < p.min_edge_bps:
        reasons.append("EDGE_TOO_LOW")
    if inp.signal_age_ms > p.max_signal_age_ms:
        reasons.append("SIGNAL_TOO_OLD")
    if inp.wallet_count < p.min_wallets:
        reasons.append("WALLET_CONFLUENCE_TOO_WEAK")
    if abs(inp.flow_imbalance) < p.min_flow_imbalance:
        notes.append("FLOW_IMBALANCE_WEAK")
    if inp.flow_volume_usdc < p.min_flow_volume_usdc:
        notes.append("FLOW_VOLUME_LOW")
    if p.block_after_move and inp.tremor_phase == "AFTER_MOVE":
        reasons.append("AFTER_MOVE_BLOCKED")
    if p.block_choppy and inp.market_regime.upper() == "CHOPPY":
        reasons.append("CHOPPY_BLOCKED")
    if inp.data_source not in p.real_sources:
        notes.append(f"NON_PRIMARY_SOURCE:{inp.data_source}")
    if inp.spread_bps > 0:
        notes.append(f"spread_bps={inp.spread_bps:.2f}")
    if inp.slippage_bps > 0:
        notes.append(f"slippage_bps={inp.slippage_bps:.2f}")

    if reasons:
        return SignalQualityDecision(QualityDecision.REJECT, score, reasons, notes)
    if score >= p.min_score:
        return SignalQualityDecision(QualityDecision.PAPER_ELIGIBLE, score, reasons, notes)
    return SignalQualityDecision(QualityDecision.WATCH, score, ["QUALITY_SCORE_BELOW_PAPER_THRESHOLD"], notes)


__all__ = [
    "QualityDecision",
    "QualityProfile",
    "SignalQualityDecision",
    "SignalQualityInput",
    "evaluate_signal_quality",
    "quality_score",
]
