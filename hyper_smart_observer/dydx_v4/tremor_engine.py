"""
dYdX v4 Tremor Engine — detection d'anomalies de marche, READ-ONLY / PAPER-ONLY.

But: rapprocher la logique du bot viral Polymarket sans copier aveuglement
un wallet. Le moteur detecte un "tremblement" de marche: variation anormale,
volume/flow anormal, wallets leaders qui precedent le mouvement, consensus, edge.

Ce module est volontairement PUR:
- aucun reseau ;
- aucun ordre ;
- aucune cle ;
- aucune ecriture obligatoire ;
- testable sans dYdX.

Un TremorEvent n'est jamais un ordre. C'est un candidat d'analyse qui peut finir
en WATCH, PAPER_CANDIDATE ou NO_TRADE.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - compat Python 3.10
    from enum import Enum

    class StrEnum(str, Enum):
        def __str__(self) -> str:
            return self.value


class TremorDecision(StrEnum):
    """Decision lisible pour dashboard/logs. Jamais un ordre reel."""

    IGNORE = "IGNORE"
    WATCH = "WATCH"
    PAPER_CANDIDATE = "PAPER_CANDIDATE"
    NO_TRADE = "NO_TRADE"


class TremorReason(StrEnum):
    """Raisons de refus/qualification specifiques au tremor."""

    TREMOR_TOO_WEAK = "TREMOR_TOO_WEAK"
    MARKET_ALREADY_MOVED = "MARKET_ALREADY_MOVED"
    NO_LEADING_WALLET = "NO_LEADING_WALLET"
    FLOW_CONFLICT = "FLOW_CONFLICT"
    EDGE_NEGATIVE_AFTER_TREMOR = "EDGE_NEGATIVE_AFTER_TREMOR"
    SIGNAL_TOO_LATE = "SIGNAL_TOO_LATE"
    CONSENSUS_TOO_WEAK = "CONSENSUS_TOO_WEAK"
    CHOPPY_MARKET = "CHOPPY_MARKET"
    LOW_CONFIDENCE_CONTEXT = "LOW_CONFIDENCE_CONTEXT"
    LARGE_TRADE_BOOST = "LARGE_TRADE_BOOST"
    PAPER_ONLY = "PAPER_ONLY"


@dataclass(frozen=True)
class TremorConfig:
    """Seuils prudents, non destructifs, adaptes a une simulation paper."""

    min_watch_score: float = 3.0
    min_paper_candidate_score: float = 3.5
    max_signal_age_ms: int = 30_000
    already_moved_bps: float = 90.0
    min_leading_wallets: int = 1
    min_consensus_wallets: int = 1
    min_edge_bps: float = 3.0
    min_flow_volume_usdc: float = 500.0
    min_flow_imbalance: float = 0.35
    min_flow_trades: int = 1
    min_market_confidence: float = 0.15
    block_choppy_market: bool = True
    allow_flow_only_watch: bool = True
    large_trade_boost_usdc: float = 50_000.0
    large_trade_boost_score: float = 1.0


@dataclass
class TremorObservation:
    """
    Donnees normalisees observees au moment du tremor.

    Tous les champs sont des observations publiques ou des metriques internes paper.
    Les valeurs inconnues doivent rester a 0/None: le moteur refuse ou classe WATCH,
    il n'invente jamais un edge.
    """

    market_id: str
    direction: str  # LONG | SHORT
    price_move_bps: float = 0.0
    volume_zscore: float = 0.0
    flow_imbalance: float = 0.0
    flow_volume_usdc: float = 0.0
    flow_trade_count: int = 0
    large_trade_usdc: float = 0.0
    leading_wallets: int = 0
    consensus_wallets: int = 0
    signal_age_ms: int = 0
    edge_remaining_bps: float | None = None
    market_regime: str = "UNKNOWN"
    market_confidence: float = 0.0
    flow_direction: str | None = None  # LONG | SHORT si connu
    source: str = "unknown"
    created_at_ms: int = 0

    def __post_init__(self) -> None:
        if not self.market_id:
            raise ValueError("market_id is required")
        if self.direction.upper() not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")


@dataclass(frozen=True)
class TremorEvent:
    """Resultat final: explicable, journalisable, jamais executable tel quel."""

    event_id: str
    market_id: str
    direction: str
    intensity_score: float
    decision: TremorDecision
    reasons: list[str] = field(default_factory=list)
    explanation: str = ""
    timeline_phase: str = "UNKNOWN"
    price_move_bps: float = 0.0
    volume_zscore: float = 0.0
    flow_imbalance: float = 0.0
    flow_volume_usdc: float = 0.0
    flow_trade_count: int = 0
    large_trade_usdc: float = 0.0
    leading_wallets: int = 0
    consensus_wallets: int = 0
    signal_age_ms: int = 0
    edge_remaining_bps: float | None = None
    market_regime: str = "UNKNOWN"
    market_confidence: float = 0.0
    source: str = "unknown"
    created_at_ms: int = 0
    read_only: bool = True
    paper_only: bool = True

    @property
    def is_actionable_paper_candidate(self) -> bool:
        return self.decision == TremorDecision.PAPER_CANDIDATE

    def to_log_dict(self) -> dict:
        """Payload pret pour DecisionLogger / dashboard."""
        return {
            "event_id": self.event_id,
            "market_id": self.market_id,
            "direction": self.direction,
            "intensity_score": self.intensity_score,
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "explanation": self.explanation,
            "timeline_phase": self.timeline_phase,
            "price_move_bps": self.price_move_bps,
            "volume_zscore": self.volume_zscore,
            "flow_imbalance": self.flow_imbalance,
            "flow_volume_usdc": self.flow_volume_usdc,
            "flow_trade_count": self.flow_trade_count,
            "large_trade_usdc": self.large_trade_usdc,
            "leading_wallets": self.leading_wallets,
            "consensus_wallets": self.consensus_wallets,
            "signal_age_ms": self.signal_age_ms,
            "edge_remaining_bps": self.edge_remaining_bps,
            "market_regime": self.market_regime,
            "market_confidence": self.market_confidence,
            "source": self.source,
            "created_at_ms": self.created_at_ms,
            "read_only": self.read_only,
            "paper_only": self.paper_only,
        }


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _score_price_move(abs_bps: float) -> float:
    # 0-3 points: 75 bps = mouvement tres fort, cap a 3.
    return _clamp(abs_bps / 75.0, 0.0, 1.0) * 3.0


def _score_volume(zscore: float) -> float:
    # 0-2 points: z=4 = volume tres anormal, cap a 2.
    return _clamp(max(0.0, zscore) / 4.0, 0.0, 1.0) * 2.0


def _score_flow(imbalance: float, volume_usdc: float, trades: int, cfg: TremorConfig) -> float:
    # 0-2 points: desequilibre + volume + nombre de trades.
    imbalance_score = _clamp((abs(imbalance) - 0.50) / 0.50, 0.0, 1.0) * 1.2
    volume_score = _clamp(volume_usdc / max(1.0, cfg.min_flow_volume_usdc * 2.0), 0.0, 1.0) * 0.5
    trades_score = _clamp(trades / max(1, cfg.min_flow_trades * 2), 0.0, 1.0) * 0.3
    return imbalance_score + volume_score + trades_score


def _score_large_trade(large_trade_usdc: float, cfg: TremorConfig) -> float:
    # 0-N points: un gros trade public frais peut renforcer le tremor sans creer un ordre.
    threshold = max(1.0, cfg.large_trade_boost_usdc)
    if large_trade_usdc < threshold:
        return 0.0
    scale = _clamp((large_trade_usdc - threshold) / threshold, 0.0, 1.0)
    return cfg.large_trade_boost_score * (0.5 + 0.5 * scale)


def _score_wallets(leading: int, consensus: int, cfg: TremorConfig) -> float:
    # 0-2 points: wallets qui precedent + consensus distinct.
    leading_score = _clamp(leading / max(1, cfg.min_leading_wallets * 2), 0.0, 1.0) * 0.8
    consensus_score = _clamp(consensus / max(1, cfg.min_consensus_wallets * 2), 0.0, 1.0) * 1.2
    return leading_score + consensus_score


def _score_freshness(age_ms: int, cfg: TremorConfig) -> float:
    # 0-1 point: decay exponentiel, zero au-dela du hard max.
    if age_ms <= 0:
        return 1.0
    if age_ms >= cfg.max_signal_age_ms:
        return 0.0
    half_life = max(1000.0, cfg.max_signal_age_ms / 3.0)
    return math.pow(0.5, age_ms / half_life)


def tremor_intensity(obs: TremorObservation, cfg: TremorConfig | None = None) -> float:
    """Score 0-10 lisible par l'utilisateur/dashboard."""
    c = cfg or TremorConfig()
    score = (
        _score_price_move(abs(obs.price_move_bps))
        + _score_volume(obs.volume_zscore)
        + _score_flow(obs.flow_imbalance, obs.flow_volume_usdc, obs.flow_trade_count, c)
        + _score_large_trade(obs.large_trade_usdc, c)
        + _score_wallets(obs.leading_wallets, obs.consensus_wallets, c)
        + _score_freshness(obs.signal_age_ms, c)
    )
    return round(_clamp(score, 0.0, 10.0), 2)


def timeline_phase(obs: TremorObservation, cfg: TremorConfig | None = None) -> str:
    """
    Classe l'observation dans une timeline avant/pendant/apres.

    BEFORE_MOVE: wallets/consensus presents mais mouvement prix encore modere.
    DURING_MOVE: tremor en cours.
    AFTER_MOVE: le marche a deja beaucoup bouge, risque d'arrivee tardive.
    """
    c = cfg or TremorConfig()
    abs_move = abs(obs.price_move_bps)
    if obs.leading_wallets >= c.min_leading_wallets and abs_move < c.already_moved_bps * 0.45:
        return "BEFORE_MOVE"
    if abs_move >= c.already_moved_bps:
        return "AFTER_MOVE"
    if abs_move >= c.already_moved_bps * 0.45 or obs.flow_imbalance >= c.min_flow_imbalance:
        return "DURING_MOVE"
    return "UNKNOWN"


def _event_id(obs: TremorObservation, score: float, now_ms: int) -> str:
    raw = (
        f"{obs.market_id}:{obs.direction}:{obs.source}:{obs.signal_age_ms}:"
        f"{round(score, 2)}:{now_ms // 1000}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def evaluate_tremor(obs: TremorObservation, cfg: TremorConfig | None = None) -> TremorEvent:
    """
    Evaluer un tremor de facon deterministe.

    Ordre logique:
    1. Calcul score 0-10.
    2. Raisons de refus strictes.
    3. Classement IGNORE/WATCH/PAPER_CANDIDATE/NO_TRADE.
    """
    c = cfg or TremorConfig()
    now_ms = obs.created_at_ms or int(time.time() * 1000)
    score = tremor_intensity(obs, c)
    phase = timeline_phase(obs, c)
    reasons: list[str] = [TremorReason.PAPER_ONLY.value]
    if obs.large_trade_usdc >= c.large_trade_boost_usdc:
        reasons.append(TremorReason.LARGE_TRADE_BOOST.value)

    if obs.signal_age_ms > c.max_signal_age_ms:
        reasons.append(TremorReason.SIGNAL_TOO_LATE.value)
    if phase == "AFTER_MOVE":
        reasons.append(TremorReason.MARKET_ALREADY_MOVED.value)
    if c.block_choppy_market and obs.market_regime.upper() == "CHOPPY":
        reasons.append(TremorReason.CHOPPY_MARKET.value)
    if 0.0 < obs.market_confidence < c.min_market_confidence:
        reasons.append(TremorReason.LOW_CONFIDENCE_CONTEXT.value)
    if obs.flow_direction and obs.flow_direction.upper() != obs.direction.upper():
        reasons.append(TremorReason.FLOW_CONFLICT.value)
    if obs.edge_remaining_bps is not None and obs.edge_remaining_bps < c.min_edge_bps:
        reasons.append(TremorReason.EDGE_NEGATIVE_AFTER_TREMOR.value)
    if score < c.min_watch_score:
        reasons.append(TremorReason.TREMOR_TOO_WEAK.value)

    has_wallet_confluence = (
        obs.leading_wallets >= c.min_leading_wallets
        and obs.consensus_wallets >= c.min_consensus_wallets
    )
    has_flow_confluence = (
        obs.flow_volume_usdc >= c.min_flow_volume_usdc
        and abs(obs.flow_imbalance) >= c.min_flow_imbalance
        and obs.flow_trade_count >= c.min_flow_trades
    )

    if not has_wallet_confluence:
        if has_flow_confluence and c.allow_flow_only_watch:
            # Flow seul peut meriter WATCH, mais pas PAPER_CANDIDATE.
            pass
        else:
            reasons.append(TremorReason.NO_LEADING_WALLET.value)
            if obs.consensus_wallets < c.min_consensus_wallets:
                reasons.append(TremorReason.CONSENSUS_TOO_WEAK.value)

    hard_blocks = {
        TremorReason.SIGNAL_TOO_LATE.value,
        TremorReason.MARKET_ALREADY_MOVED.value,
        TremorReason.CHOPPY_MARKET.value,
        TremorReason.FLOW_CONFLICT.value,
        TremorReason.EDGE_NEGATIVE_AFTER_TREMOR.value,
    }
    if any(r in hard_blocks for r in reasons):
        decision = TremorDecision.NO_TRADE
    elif score >= c.min_paper_candidate_score and has_wallet_confluence:
        decision = TremorDecision.PAPER_CANDIDATE
    elif score >= c.min_watch_score or has_flow_confluence:
        decision = TremorDecision.WATCH
    else:
        decision = TremorDecision.IGNORE

    explanation = build_explanation(obs, score, phase, decision, reasons)
    return TremorEvent(
        event_id=_event_id(obs, score, now_ms),
        market_id=obs.market_id,
        direction=obs.direction.upper(),
        intensity_score=score,
        decision=decision,
        reasons=reasons,
        explanation=explanation,
        timeline_phase=phase,
        price_move_bps=obs.price_move_bps,
        volume_zscore=obs.volume_zscore,
        flow_imbalance=obs.flow_imbalance,
        flow_volume_usdc=obs.flow_volume_usdc,
        flow_trade_count=obs.flow_trade_count,
        large_trade_usdc=obs.large_trade_usdc,
        leading_wallets=obs.leading_wallets,
        consensus_wallets=obs.consensus_wallets,
        signal_age_ms=obs.signal_age_ms,
        edge_remaining_bps=obs.edge_remaining_bps,
        market_regime=obs.market_regime,
        market_confidence=obs.market_confidence,
        source=obs.source,
        created_at_ms=now_ms,
    )


def build_explanation(
    obs: TremorObservation,
    score: float,
    phase: str,
    decision: TremorDecision,
    reasons: list[str],
) -> str:
    """Phrase courte et lisible pour logs/dashboard."""
    parts = [
        f"{obs.market_id} {obs.direction.upper()} tremor={score:.2f}/10",
        f"phase={phase}",
        f"move={obs.price_move_bps:.1f}bps",
        f"vol_z={obs.volume_zscore:.2f}",
        f"flow={obs.flow_imbalance:.2f}/{obs.flow_volume_usdc:.0f}USDC/{obs.flow_trade_count}trades",
        f"large_trade={obs.large_trade_usdc:.0f}USDC",
        f"wallets={obs.leading_wallets}/{obs.consensus_wallets}",
        f"age={obs.signal_age_ms}ms",
        f"decision={decision.value}",
    ]
    if obs.edge_remaining_bps is not None:
        parts.append(f"edge={obs.edge_remaining_bps:.1f}bps")
    if reasons:
        parts.append("reasons=" + ",".join(reasons))
    return " | ".join(parts)


def observation_from_flow(
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
    created_at_ms: int | None = None,
) -> TremorObservation:
    """Factory pratique pour brancher MarketFlowMonitor sans dependance import."""
    return TremorObservation(
        market_id=market_id,
        direction=direction,
        price_move_bps=price_move_bps,
        volume_zscore=volume_zscore,
        flow_imbalance=flow_imbalance,
        flow_volume_usdc=flow_volume_usdc,
        flow_trade_count=flow_trade_count,
        large_trade_usdc=large_trade_usdc,
        leading_wallets=0,
        consensus_wallets=0,
        signal_age_ms=signal_age_ms,
        edge_remaining_bps=edge_remaining_bps,
        market_regime=market_regime,
        market_confidence=market_confidence,
        flow_direction=direction,
        source="market_flow",
        created_at_ms=created_at_ms or int(time.time() * 1000),
    )


def observation_from_cluster(
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
    created_at_ms: int | None = None,
) -> TremorObservation:
    """Factory pratique pour brancher ClusterSignal sans importer live_observer."""
    return TremorObservation(
        market_id=market_id,
        direction=direction,
        price_move_bps=price_move_bps,
        volume_zscore=volume_zscore,
        flow_imbalance=flow_imbalance,
        flow_volume_usdc=total_notional_usdc,
        flow_trade_count=flow_trade_count,
        large_trade_usdc=large_trade_usdc,
        leading_wallets=max(0, wallet_count),
        consensus_wallets=max(0, wallet_count),
        signal_age_ms=max(0, signal_age_ms),
        edge_remaining_bps=edge_remaining_bps,
        market_regime=market_regime,
        market_confidence=market_confidence,
        flow_direction=direction,
        source=source,
        created_at_ms=created_at_ms or int(time.time() * 1000),
    )


__all__ = [
    "TremorConfig",
    "TremorDecision",
    "TremorEvent",
    "TremorObservation",
    "TremorReason",
    "build_explanation",
    "evaluate_tremor",
    "observation_from_cluster",
    "observation_from_flow",
    "timeline_phase",
    "tremor_intensity",
]
