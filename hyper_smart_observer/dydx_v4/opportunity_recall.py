from __future__ import annotations

from dataclasses import dataclass
from typing import Any


HARD_REASON_FRAGMENTS = (
    "NO_EDGE",
    "QUALITY_TOO_LOW",
    "RISK_TOO_HIGH",
    "AFTER_MOVE",
    "HARD_DAILY_LOSS",
    "HARD_CONSECUTIVE_LOSS",
    "MAX_OPEN_POSITIONS",
    "SAME_MARKET_LIMIT",
    "SAME_MARKET_COOLDOWN",
)


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class RecallDecision:
    should_recall: bool
    notional_usdc: float
    reasons: list[str]
    notes: list[str]
    read_only: bool = True
    paper_only: bool = True

    def to_dict(self) -> dict:
        return {
            "should_recall": self.should_recall,
            "notional_usdc": round(self.notional_usdc, 6),
            "reasons": list(self.reasons),
            "notes": list(self.notes),
            "read_only": self.read_only,
            "paper_only": self.paper_only,
        }


def _has_hard_reason(reasons: list[str]) -> bool:
    text = "|".join(str(r) for r in reasons)
    return any(fragment in text for fragment in HARD_REASON_FRAGMENTS)


def evaluate_opportunity_recall(
    tuned: Any,
    director: dict,
    reasons: list[str],
    *,
    base_notional_usdc: float = 12.0,
    max_notional_usdc: float = 100.0,
) -> RecallDecision:
    tremor = getattr(tuned, "tremor", None)
    quality = getattr(tuned, "quality", None)
    edge_bps = _num(getattr(tremor, "edge_remaining_bps", 0.0))
    tremor_score = _num(getattr(tremor, "intensity_score", 0.0))
    quality_score = _num(getattr(quality, "score", 0.0))
    age_ms = _num(getattr(tremor, "signal_age_ms", 0.0))
    leading = _num(getattr(tremor, "leading_wallets", 0.0))
    consensus = _num(getattr(tremor, "consensus_wallets", 0.0))
    phase = str(getattr(tremor, "timeline_phase", "") or "")
    opportunity = _num(director.get("opportunity_score", 0.0)) if isinstance(director, dict) else 0.0
    risk = _num(director.get("risk_score", 100.0)) if isinstance(director, dict) else 100.0

    out_reasons: list[str] = []
    notes: list[str] = []
    if _has_hard_reason(reasons):
        return RecallDecision(False, 0.0, ["RECALL_HARD_REASON_PRESENT"], notes)
    if phase == "AFTER_MOVE":
        return RecallDecision(False, 0.0, ["RECALL_AFTER_MOVE"], notes)
    if age_ms > 90_000:
        return RecallDecision(False, 0.0, ["RECALL_SIGNAL_TOO_OLD"], notes)
    if edge_bps < 4.0:
        out_reasons.append("RECALL_EDGE_TOO_LOW")
    if quality_score < 58.0:
        out_reasons.append("RECALL_QUALITY_TOO_LOW")
    if tremor_score < 6.2:
        out_reasons.append("RECALL_TREMOR_TOO_LOW")
    if max(leading, consensus) < 2:
        out_reasons.append("RECALL_CONSENSUS_TOO_WEAK")
    if opportunity < 62.0:
        out_reasons.append("RECALL_OPPORTUNITY_TOO_LOW")
    if risk > 52.0:
        out_reasons.append("RECALL_RISK_TOO_HIGH")
    if out_reasons:
        return RecallDecision(False, 0.0, out_reasons, notes)

    quality_factor = min(1.0, max(0.30, (quality_score - 58.0) / 32.0))
    edge_factor = min(1.0, max(0.30, edge_bps / 18.0))
    risk_factor = min(1.0, max(0.20, 1.0 - risk / 100.0))
    notional = min(max_notional_usdc, max(0.0, base_notional_usdc * quality_factor * edge_factor * risk_factor))
    notes.append("recall_second_chance_micro_paper")
    notes.append(f"recall_edge={edge_bps:.2f}")
    notes.append(f"recall_quality={quality_score:.2f}")
    notes.append(f"recall_risk={risk:.2f}")
    return RecallDecision(True, notional, ["RECALL_PROMISING_MISSED_OPPORTUNITY"], notes)


__all__ = ["RecallDecision", "evaluate_opportunity_recall"]
