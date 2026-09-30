from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class DirectorAssessment:
    opportunity_score: float
    risk_score: float
    net_score: float
    size_multiplier: float
    hard_block: bool
    reasons: list[str]
    notes: list[str]
    profile: dict | None = None
    read_only: bool = True
    paper_only: bool = True

    def to_dict(self) -> dict:
        return {
            "opportunity_score": round(self.opportunity_score, 4),
            "risk_score": round(self.risk_score, 4),
            "net_score": round(self.net_score, 4),
            "size_multiplier": round(self.size_multiplier, 4),
            "hard_block": self.hard_block,
            "reasons": list(self.reasons),
            "notes": list(self.notes),
            "profile": dict(self.profile or {}),
            "read_only": self.read_only,
            "paper_only": self.paper_only,
        }


def assess_decision_intelligence(tuned: Any, health: Any, state: Any, ctx: Any) -> DirectorAssessment:
    tremor = getattr(tuned, "tremor", None)
    quality = getattr(tuned, "quality", None)
    reasons: list[str] = []
    notes: list[str] = []

    tremor_score = _num(getattr(tremor, "intensity_score", 0.0))
    quality_score = _num(getattr(quality, "score", 0.0))
    edge_bps = _num(getattr(tremor, "edge_remaining_bps", 0.0))
    age_ms = _num(getattr(tremor, "signal_age_ms", 0.0))
    leading_wallets = _num(getattr(tremor, "leading_wallets", 0.0))
    consensus_wallets = _num(getattr(tremor, "consensus_wallets", 0.0))
    market_confidence = _num(getattr(tremor, "market_confidence", 0.0))
    phase = str(getattr(tremor, "timeline_phase", "") or "")
    source = str(getattr(tremor, "source", "") or "")
    market_id = str(getattr(tremor, "market_id", "") or "")
    direction = str(getattr(tremor, "direction", "") or "")

    closed_trades = _num(getattr(health, "closed_trades", 0.0))
    winrate = _num(getattr(health, "winrate", 0.0))
    profit_factor = _num(getattr(health, "profit_factor", 0.0))
    consecutive_losses = _num(getattr(health, "consecutive_losses", 0.0))
    daily_pnl = _num(getattr(health, "daily_pnl_usdc", 0.0))

    opportunity = 0.0
    opportunity += _clamp(tremor_score / 10.0, 0.0, 1.0) * 24.0
    opportunity += _clamp(quality_score / 100.0, 0.0, 1.0) * 24.0
    opportunity += _clamp(edge_bps / 18.0, 0.0, 1.0) * 16.0
    opportunity += _clamp(max(leading_wallets, consensus_wallets) / 5.0, 0.0, 1.0) * 10.0
    opportunity += _clamp(market_confidence, 0.0, 1.0) * 8.0
    opportunity += _clamp(1.0 - age_ms / 90_000.0, 0.0, 1.0) * 8.0
    if closed_trades >= 30 and winrate >= 0.56:
        opportunity += 5.0
        notes.append("director_winrate_lift")
    if closed_trades >= 30 and profit_factor >= 1.35:
        opportunity += 5.0
        notes.append("director_profit_factor_lift")

    risk = 0.0
    risk += _clamp(_num(getattr(health, "fallback_share", 0.0)) / 0.50, 0.0, 1.0) * 14.0
    risk += _clamp(consecutive_losses / 6.0, 0.0, 1.0) * 20.0
    risk += _clamp(abs(min(0.0, daily_pnl)) / 45.0, 0.0, 1.0) * 20.0
    risk += _clamp(_num(getattr(ctx, "spread_bps", 0.0)) / 35.0, 0.0, 1.0) * 9.0
    risk += _clamp(_num(getattr(ctx, "slippage_bps", 0.0)) / 16.0, 0.0, 1.0) * 9.0
    risk += _clamp(_num(getattr(state, "same_market_open_positions", 0.0)) / 3.0, 0.0, 1.0) * 8.0

    profile_dict: dict | None = None
    profile_size = 1.0
    profile_block = False
    try:
        from hyper_smart_observer.dydx_v4.paper_profile_memory import profile_bias_for
        profile = profile_bias_for(market_id, direction, source)
        profile_dict = profile.to_dict()
        opportunity += profile.opportunity_delta
        risk += profile.risk_delta
        profile_size = profile.size_multiplier
        profile_block = profile.hard_block
        reasons += profile.reasons
        notes += profile.notes
    except Exception:
        notes.append("profile_memory_unavailable")

    if closed_trades >= 30 and winrate < 0.50:
        risk += 14.0
        reasons.append("DIRECTOR_LOW_SESSION_WINRATE")
    if closed_trades >= 30 and profit_factor < 1.05:
        risk += 14.0
        reasons.append("DIRECTOR_LOW_SESSION_PROFIT_FACTOR")
    if phase == "AFTER_MOVE":
        risk += 20.0
        reasons.append("DIRECTOR_AFTER_MOVE_RISK")
    if source and source.lower() in {"demo", "fallback"}:
        risk += 12.0
        reasons.append("DIRECTOR_WEAK_SOURCE")
    if age_ms > 60_000:
        risk += 10.0
        reasons.append("DIRECTOR_LATE_SIGNAL")

    opportunity = _clamp(opportunity, 0.0, 100.0)
    risk = _clamp(risk, 0.0, 100.0)
    net = _clamp(opportunity - risk, 0.0, 100.0)
    if opportunity >= 82 and risk <= 24 and (closed_trades < 30 or winrate >= 0.54):
        multiplier = 1.15
        notes.append("director_high_quality_winrate_boost")
    elif opportunity >= 66 and risk <= 40 and (closed_trades < 30 or winrate >= 0.50):
        multiplier = 1.00
        notes.append("director_normal_quality_winrate_ok")
    elif opportunity >= 52 and risk <= 52:
        multiplier = 0.45
        notes.append("director_reduced_quality_winrate_guard")
    elif opportunity >= 35 and risk <= 65:
        multiplier = 0.25
        notes.append("director_minimal_quality_exploration")
    else:
        multiplier = 0.0
        reasons.append("DIRECTOR_LOW_NET_SCORE")
    multiplier *= profile_size

    hard_block = False
    if edge_bps <= 0:
        hard_block = True
        reasons.append("DIRECTOR_NO_EDGE")
    if quality_score < 25:
        hard_block = True
        reasons.append("DIRECTOR_QUALITY_TOO_LOW")
    if closed_trades >= 50 and winrate < 0.45 and profit_factor < 1.0:
        hard_block = True
        reasons.append("DIRECTOR_SESSION_NOT_WINNING")
    if profile_block:
        hard_block = True
        reasons.append("DIRECTOR_PROFILE_MEMORY_BLOCK")
    if risk >= 85 and opportunity < 82:
        hard_block = True
        reasons.append("DIRECTOR_RISK_TOO_HIGH")
    if hard_block:
        multiplier = 0.0

    return DirectorAssessment(
        opportunity_score=round(opportunity, 4),
        risk_score=round(risk, 4),
        net_score=round(net, 4),
        size_multiplier=round(_clamp(multiplier, 0.0, 1.25), 4),
        hard_block=hard_block,
        reasons=reasons,
        notes=notes,
        profile=profile_dict,
    )


__all__ = ["DirectorAssessment", "assess_decision_intelligence"]
