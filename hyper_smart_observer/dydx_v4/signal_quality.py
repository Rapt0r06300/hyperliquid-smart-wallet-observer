"""dYdX v4 paper signal quality gate.

Pure, read-only scoring layer used before paper simulation. It combines tremor
phase, intensity, market context, flow, wallet confluence, edge and data source.
It never opens orders and never mutates logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict
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


leader_market_stats: dict[str, dict[str, dict[str, int]]] = defaultdict(dict)


def update_leader_stats(wallet: str, market: str, *, won: bool) -> None:
    """Update in-memory leader/market outcome stats for paper scoring.

    The function stores only aggregate win/total counts. It is intentionally
    local and read-only with respect to exchanges; it never places orders.
    """
    wallet_key = str(wallet or "").strip().lower()
    market_key = str(market or "").strip().upper()
    if not wallet_key or not market_key:
        return
    row = leader_market_stats.setdefault(wallet_key, {}).setdefault(market_key, {"wins": 0, "total": 0})
    row["total"] = int(row.get("total", 0)) + 1
    if won:
        row["wins"] = int(row.get("wins", 0)) + 1


def reset_leader_stats() -> None:
    leader_market_stats.clear()


def _leader_market_winrate(wallet: str, market: str) -> tuple[float, int] | None:
    wallet_key = str(wallet or "").strip().lower()
    market_key = str(market or "").strip().upper()
    row = leader_market_stats.get(wallet_key, {}).get(market_key)
    if not row:
        return None
    total = int(row.get("total", 0) or 0)
    if total <= 0:
        return None
    wins = int(row.get("wins", 0) or 0)
    return wins / total, total


@dataclass(frozen=True)
class QualityProfile:
    min_score: float = 50.0
    watch_score: float = 35.0
    min_tremor_score: float = 3.0
    watch_tremor_score: float = 2.0
    min_edge_bps: float = 3.0
    watch_edge_bps: float = 1.5
    max_signal_age_ms: int = 30_000
    soft_age_ms: int = 18_000
    min_wallets: int = 1
    min_flow_imbalance: float = 0.40
    min_flow_volume_usdc: float = 1_000.0
    max_spread_bps: float = 35.0
    max_slippage_bps: float = 14.0
    block_after_move: bool = True
    block_choppy: bool = True
    real_sources: set[str] = field(default_factory=lambda: {"REAL_INDEXER", "orderbook_real", "stream", "rest", "wallet_cluster", "market_flow"})


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
    leader_wallet: str = ""


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
    if inp.spread_bps > 0:
        score -= _clamp(inp.spread_bps / max(1.0, p.max_spread_bps), 0.0, 1.0) * 4.0
    if inp.slippage_bps > 0:
        score -= _clamp(inp.slippage_bps / max(1.0, p.max_slippage_bps), 0.0, 1.0) * 4.0
    if inp.data_source not in p.real_sources:
        score -= 4.0
    if inp.tremor_phase == "BEFORE_MOVE":
        score += 5.0
    elif inp.tremor_phase == "DURING_MOVE":
        score += 2.5
    elif inp.tremor_phase == "AFTER_MOVE":
        score -= 8.0
    if inp.market_regime.upper() == "TRENDING":
        score += 2.0
    elif inp.market_regime.upper() == "CHOPPY":
        score -= 8.0
    leader_market = _leader_market_winrate(inp.leader_wallet, inp.market_id)
    if leader_market is not None:
        winrate, _total = leader_market
        if winrate < 0.40:
            score *= 0.50
    return round(_clamp(score, 0.0, 100.0), 4)


def _has_strong_flow(inp: SignalQualityInput, p: QualityProfile) -> bool:
    return (
        abs(inp.flow_imbalance) >= p.min_flow_imbalance
        and inp.flow_volume_usdc >= p.min_flow_volume_usdc
        and inp.tremor_score >= p.watch_tremor_score
        and inp.edge_remaining_bps >= p.watch_edge_bps
    )


def evaluate_signal_quality(inp: SignalQualityInput, profile: QualityProfile | None = None) -> SignalQualityDecision:
    p = profile or QualityProfile()
    score = quality_score(inp, p)
    hard: list[str] = []
    soft: list[str] = []
    notes: list[str] = []

    if inp.tremor_score < p.watch_tremor_score:
        hard.append("TREMOR_SCORE_TOO_LOW")
    elif inp.tremor_score < p.min_tremor_score:
        soft.append("TREMOR_SCORE_WATCH_ZONE")
    if inp.edge_remaining_bps < p.watch_edge_bps:
        hard.append("EDGE_TOO_LOW")
    elif inp.edge_remaining_bps < p.min_edge_bps:
        soft.append("EDGE_WATCH_ZONE")
    if inp.signal_age_ms > p.max_signal_age_ms:
        hard.append("SIGNAL_TOO_OLD")
    elif inp.signal_age_ms > p.soft_age_ms:
        soft.append("SIGNAL_AGE_WATCH_ZONE")
    if inp.wallet_count < p.min_wallets:
        if _has_strong_flow(inp, p):
            soft.append("WALLET_CONFLUENCE_WEAK_BUT_FLOW_STRONG")
        else:
            hard.append("WALLET_CONFLUENCE_TOO_WEAK")
    if abs(inp.flow_imbalance) < p.min_flow_imbalance:
        notes.append("FLOW_IMBALANCE_WEAK")
    if inp.flow_volume_usdc < p.min_flow_volume_usdc:
        notes.append("FLOW_VOLUME_LOW")
    if p.block_after_move and inp.tremor_phase == "AFTER_MOVE":
        hard.append("AFTER_MOVE_BLOCKED")
    if p.block_choppy and inp.market_regime.upper() == "CHOPPY":
        hard.append("CHOPPY_BLOCKED")
    if inp.spread_bps > p.max_spread_bps:
        hard.append("SPREAD_TOO_WIDE")
    if inp.slippage_bps > p.max_slippage_bps:
        hard.append("SLIPPAGE_TOO_HIGH")
    leader_market = _leader_market_winrate(inp.leader_wallet, inp.market_id)
    if leader_market is not None:
        winrate, total = leader_market
        notes.append(f"leader_market_winrate={winrate:.2f} total={total}")
        if winrate < 0.40:
            soft.append("LEADER_MARKET_WINRATE_LOW")
    if inp.data_source not in p.real_sources:
        notes.append(f"NON_PRIMARY_SOURCE:{inp.data_source}")
    if inp.spread_bps > 0:
        notes.append(f"spread_bps={inp.spread_bps:.2f}")
    if inp.slippage_bps > 0:
        notes.append(f"slippage_bps={inp.slippage_bps:.2f}")

    if hard:
        return SignalQualityDecision(QualityDecision.REJECT, score, hard, notes + soft)
    if score >= p.min_score and not soft:
        return SignalQualityDecision(QualityDecision.PAPER_ELIGIBLE, score, [], notes)
    if score >= p.watch_score or soft:
        return SignalQualityDecision(QualityDecision.WATCH, score, soft or ["QUALITY_SCORE_WATCH_ZONE"], notes)
    return SignalQualityDecision(QualityDecision.REJECT, score, ["QUALITY_SCORE_TOO_LOW"], notes + soft)


__all__ = [
    "QualityDecision",
    "QualityProfile",
    "SignalQualityDecision",
    "SignalQualityInput",
    "evaluate_signal_quality",
    "leader_market_stats",
    "quality_score",
    "reset_leader_stats",
    "update_leader_stats",
]
