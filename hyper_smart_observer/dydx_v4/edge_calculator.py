"""
Calculateur d'edge dYdX v4 — formule recalibrée pour REST polling réaliste.

Changements vs version initiale:
1. Freshness decay EXPONENTIEL (half-life 8s) au lieu de linéaire → signal
   encore exploitable à 12s (0.35 au lieu de 0.20)
2. delay_cost_bps SUPPRIMÉ (double-comptage avec freshness decay)
3. consensus_factor(1) relevé de 0.50 → 0.75 (single-wallet = normal sur dYdX)
4. DEFAULT_LEADER_EDGE_BPS relevé de 15 → 25 bps (basé sur les whale wallets dYdX)
5. fee_bps: seule la moitié du round-trip à l'évaluation (entry + marge exit)
6. MIN_EDGE_BPS réduit de 8 → 3 bps (filtre les trades clairement mauvais,
   laisse passer les trades à edge modeste mais positif)

PAPER-ONLY. Aucun ordre réel. Aucune clé privée.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Seuils recalibrés ────────────────────────────────────────────────────────
MIN_EDGE_BPS: float = 3.0           # seuil: filtre le bruit, laisse passer les trades modestes
TAKER_FEE_BPS: float = 5.0          # frais taker dYdX v4 (0.05%)
ROUND_TRIP_FEE_BPS: float = 10.0    # entrée + sortie (référence)
EVAL_FEE_BPS: float = 5.0           # à l'évaluation: entry taker fee only (exit counted at close)

# Freshness: décroissance exponentielle avec half-life de 12s
# À 0s: 1.0 | 5s: 0.75 | 8s: 0.63 | 12s: 0.50 | 18s: 0.35 | 25s: 0.23
FRESHNESS_HALF_LIFE_MS: int = 12_000
MAX_SIGNAL_AGE_MS: int = 30_000     # hard cutoff (au-delà = 0)

# Leader edge par défaut si inconnu (bps) — optimisé pour dYdX whales
DEFAULT_LEADER_EDGE_BPS: float = 30.0

# Crowding penalty: si >5 wallets identiques → risque de crowding
CROWDING_THRESHOLD: int = 5
CROWDING_PENALTY_BPS: float = 2.0


@dataclass
class EdgeComponents:
    """Décomposition de l'edge pour audit / no-trade logging."""
    leader_expected_edge_bps: float = 0.0
    leader_consistency_factor: float = 1.0
    signal_freshness_score: float = 1.0
    consensus_factor: float = 1.0
    # Coûts (tous positifs = déductibles)
    delay_cost_bps: float = 0.0
    spread_bps: float = 3.0
    slippage_bps: float = 1.0
    fee_bps: float = EVAL_FEE_BPS
    liquidity_penalty_bps: float = 0.0
    adverse_price_move_bps: float = 0.0
    crowding_penalty_bps: float = 0.0
    funding_penalty_bps: float = 0.0
    market_edge_multiplier: float = 1.0
    # Résultat
    edge_remaining_bps: float = 0.0
    accepted: bool = False
    reject_reason: str = ""

    @property
    def gross_edge_bps(self) -> float:
        """Edge brut avant coûts."""
        return (
            self.leader_expected_edge_bps
            * self.leader_consistency_factor
            * self.signal_freshness_score
            * self.consensus_factor
            * self.market_edge_multiplier
        )

    @property
    def total_cost_bps(self) -> float:
        return (
            self.delay_cost_bps
            + self.spread_bps
            + self.slippage_bps
            + self.fee_bps
            + self.liquidity_penalty_bps
            + self.adverse_price_move_bps
            + self.crowding_penalty_bps
            + self.funding_penalty_bps
        )

    def to_notes(self) -> list[str]:
        return [
            f"leader_edge={self.leader_expected_edge_bps:.1f}bps",
            f"freshness={self.signal_freshness_score:.2f}",
            f"consensus={self.consensus_factor:.2f}",
            f"market_mult={self.market_edge_multiplier:.2f}",
            f"gross={self.gross_edge_bps:.1f}bps",
            f"costs={self.total_cost_bps:.1f}bps",
            f"edge_net={self.edge_remaining_bps:.1f}bps",
            f"accepted={self.accepted}",
        ]


def signal_freshness_score(signal_age_ms: int) -> float:
    """
    Score de fraîcheur — décroissance exponentielle (half-life 12s).

    0ms  → 1.00
    5s   → 0.75
    8s   → 0.63
    12s  → 0.50  (half-life)
    18s  → 0.35
    25s  → 0.23
    >30s → 0.00  (hard cutoff)
    """
    if signal_age_ms <= 0:
        return 1.0
    if signal_age_ms >= MAX_SIGNAL_AGE_MS:
        return 0.0
    return math.pow(0.5, signal_age_ms / FRESHNESS_HALF_LIFE_MS)


def leader_consistency_factor(
    winrate: float,
    profit_factor: float,
    trade_count: int = 0,
) -> float:
    """
    Facteur de confiance dans le leader.

    1.0 si winrate >= 60% et profit_factor >= 2.0
    0.9 si winrate >= 55%
    0.8 si winrate >= 50%
    0.7 si inconnu (relevé de 0.6 → 0.7: moins punitif pour les nouveaux leaders)
    """
    if winrate <= 0 and profit_factor <= 0:
        return 0.8  # inconnu → modérément conservateur

    if winrate >= 0.60 and profit_factor >= 2.0:
        factor = 1.0
    elif winrate >= 0.55:
        factor = 0.9
    elif winrate >= 0.50:
        factor = 0.8
    elif winrate >= 0.45:
        factor = 0.7
    elif winrate >= 0.40:
        factor = 0.55
    else:
        return 0.0

    # Bonus confiance si historique long
    if trade_count >= 50:
        factor = min(1.0, factor * 1.05)
    elif trade_count < 10:
        factor *= 0.90  # pénalité faible historique (adoucie)

    return factor


def consensus_factor(wallet_count: int) -> float:
    """
    Bonus de consensus si plusieurs wallets s'alignent.

    1 wallet = 0.75 (single-wallet = normal sur dYdX, relevé de 0.5)
    2 wallets = base (1.0)
    3+ = bonus (cap 1.18)
    """
    if wallet_count <= 1:
        return 0.92  # single-wallet: normal sur dYdX, minimal reduction
    if wallet_count == 2:
        return 1.0
    if wallet_count == 3:
        return 1.10
    if wallet_count == 4:
        return 1.15
    return 1.18  # cap à 5+, crowding penalty séparément


def _market_context_edge_multiplier(market_context: object | None) -> float:
    """Apply explicit regime and volume multipliers to edge.

    RANGING markets are not allowed to create paper edge. TRENDING markets get
    a controlled boost. Volume confirms momentum when z-score is high and cuts
    edge when participation is weak.
    """
    if market_context is None:
        return 1.0
    mult = 1.0
    regime = str(getattr(market_context, "regime", "") or "").upper()
    if regime == "RANGING":
        mult *= 0.0
    elif regime == "TRENDING":
        mult *= 1.2
    try:
        volume_z = float(getattr(market_context, "volume_zscore", 0.0) or 0.0)
    except (TypeError, ValueError):
        volume_z = 0.0
    if volume_z > 1.0:
        mult *= 1.2
    elif volume_z < -1.0:
        mult *= 0.5
    return max(0.0, mult)


def leader_expected_edge_bps(
    account_score_expectancy_usdc: float = 0.0,
    avg_trade_size_usdc: float = 50.0,
    fallback_bps: float = DEFAULT_LEADER_EDGE_BPS,
) -> float:
    """
    Estimation de l'edge attendu en bps.

    Sans donnée historique → fallback 30 bps (whale dYdX).
    """
    if avg_trade_size_usdc > 0 and account_score_expectancy_usdc != 0:
        edge_bps = (account_score_expectancy_usdc / avg_trade_size_usdc) * 10_000
        return max(0.0, min(edge_bps, 100.0))
    return fallback_bps


def calculate_edge(
    signal_age_ms: int,
    wallet_count: int,
    leader_winrate: float = 0.0,
    leader_profit_factor: float = 0.0,
    leader_trade_count: int = 0,
    leader_expectancy_usdc: float = 0.0,
    paper_notional_usdc: float = 50.0,
    spread_bps: float = 3.0,
    slippage_bps: float = 1.0,
    fee_bps: float = EVAL_FEE_BPS,
    delay_ms: int = 500,
    liquidity_penalty_bps: float = 0.0,
    adverse_price_move_bps: float = 0.0,
    funding_penalty_bps: float = 0.0,
    market_edge_multiplier: float = 1.0,
    min_edge_bps: float = MIN_EDGE_BPS,
    market_context: object | None = None,
) -> EdgeComponents:
    """
    Calculer l'edge net après tous les coûts.

    Recalibré: freshness exponentielle, pas de double-comptage delay,
    fees réduits à entry+marge.
    """
    context_multiplier = _market_context_edge_multiplier(market_context)
    result = EdgeComponents(
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        fee_bps=fee_bps,
        liquidity_penalty_bps=liquidity_penalty_bps,
        adverse_price_move_bps=adverse_price_move_bps,
        funding_penalty_bps=funding_penalty_bps,
        market_edge_multiplier=max(0.0, market_edge_multiplier) * context_multiplier,
    )

    # 1. Freshness (exponentielle, half-life 8s)
    result.signal_freshness_score = signal_freshness_score(signal_age_ms)
    if result.signal_freshness_score <= 0.0:
        result.edge_remaining_bps = -999.0
        result.accepted = False
        result.reject_reason = f"STALE_SIGNAL age={signal_age_ms}ms"
        return result

    # 2. Consistency du leader
    result.leader_consistency_factor = leader_consistency_factor(
        leader_winrate, leader_profit_factor, leader_trade_count
    )

    # 3. Edge attendu du leader
    result.leader_expected_edge_bps = leader_expected_edge_bps(
        account_score_expectancy_usdc=leader_expectancy_usdc,
        avg_trade_size_usdc=paper_notional_usdc,
    )

    # 4. Consensus
    result.consensus_factor = consensus_factor(wallet_count)

    # 5. Délai → SUPPRIMÉ (double-comptage avec freshness decay)
    # Le signal_age EST le delay. La freshness exponentielle en tient déjà compte.
    result.delay_cost_bps = 0.0

    # 6. Crowding penalty
    if wallet_count >= CROWDING_THRESHOLD:
        result.crowding_penalty_bps = CROWDING_PENALTY_BPS

    # 7. Calcul final
    gross = (
        result.leader_expected_edge_bps
        * result.leader_consistency_factor
        * result.signal_freshness_score
        * result.consensus_factor
        * result.market_edge_multiplier
    )
    result.edge_remaining_bps = gross - result.total_cost_bps

    # 8. Décision
    if result.edge_remaining_bps >= min_edge_bps:
        result.accepted = True
    else:
        result.accepted = False
        result.reject_reason = (
            f"EDGE_TOO_LOW: net={result.edge_remaining_bps:.1f}bps < min={min_edge_bps:.1f}bps"
            f" (gross={gross:.1f}bps - costs={result.total_cost_bps:.1f}bps)"
        )

    logger.debug(
        "edge_calc: age=%dms wallets=%d gross=%.1f costs=%.1f net=%.1f accepted=%s",
        signal_age_ms, wallet_count, gross, result.total_cost_bps,
        result.edge_remaining_bps, result.accepted,
     )
    return result
