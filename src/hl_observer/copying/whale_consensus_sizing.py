"""Sizing proportionnel au consensus whale (portage idée n°1 de la matrice).

Distillé de whale-wallet-mirror-copy-trader: la taille copiée doit refléter la
force du consensus (nombre de wallets frais alignés), la fraîcheur du cluster
et le notional réel engagé par les leaders. Version HyperSmart, conservatrice:

- le multiplicateur est TOUJOURS <= 1.0 (ne peut que réduire la taille);
- jamais de martingale, jamais d'augmentation au-delà du cap PaperEngine;
- pur et déterministe: aucune I/O, aucune donnée inventée;
- si une mesure requise manque, on renvoie le multiplicateur plancher avec
  une raison explicite (pas de valeur magique silencieuse).

Activation runtime via HYPERSMART_WHALE_CONSENSUS_SIZING=1 (défaut OFF tant
que le replay A/B dédié n'a pas prouvé une amélioration du profit factor net).
"""

from __future__ import annotations

from dataclasses import dataclass

FLOOR_MULTIPLIER = 0.30


@dataclass(frozen=True, slots=True)
class WhaleConsensusSizing:
    multiplier: float
    consensus_factor: float
    freshness_factor: float
    notional_factor: float
    tier: str
    reasons: tuple[str, ...]
    paper_only: bool = True
    real_execution: bool = False


def _consensus_factor(wallet_count: int) -> tuple[float, str]:
    if wallet_count >= 4:
        return 1.00, "CONSENSUS_STRONG_4PLUS_WALLETS"
    if wallet_count == 3:
        return 0.85, "CONSENSUS_GOOD_3_WALLETS"
    if wallet_count == 2:
        return 0.60, "CONSENSUS_MINIMAL_2_WALLETS"
    return FLOOR_MULTIPLIER, "CONSENSUS_SINGLE_WALLET"


def _freshness_factor(max_signal_age_ms: int) -> tuple[float, str]:
    age = max(0, int(max_signal_age_ms))
    if age <= 2_000:
        return 1.00, "CLUSTER_FRESH_UNDER_2S"
    if age <= 4_000:
        return 0.85, "CLUSTER_FRESH_UNDER_4S"
    return 0.70, "CLUSTER_AGING_OVER_4S"


def _notional_factor(total_notional_usdc: float) -> tuple[float, str]:
    notional = max(0.0, float(total_notional_usdc or 0.0))
    if notional >= 25_000.0:
        return 1.00, "LEADER_NOTIONAL_WHALE_25K_PLUS"
    if notional >= 10_000.0:
        return 0.90, "LEADER_NOTIONAL_MEDIUM_10K_PLUS"
    return 0.75, "LEADER_NOTIONAL_SMALL_UNDER_10K"


def compute_whale_consensus_sizing(
    *,
    wallet_count: int,
    max_signal_age_ms: int,
    total_notional_usdc: float,
) -> WhaleConsensusSizing:
    """Multiplicateur de marge paper en fonction de la preuve du consensus.

    Produit du facteur consensus, fraîcheur et notional leaders, borné à
    [FLOOR_MULTIPLIER, 1.0]. Ne dépend d'aucun état global.
    """

    consensus, consensus_reason = _consensus_factor(int(wallet_count))
    freshness, freshness_reason = _freshness_factor(int(max_signal_age_ms))
    notional, notional_reason = _notional_factor(float(total_notional_usdc))
    raw = consensus * freshness * notional
    multiplier = min(1.0, max(FLOOR_MULTIPLIER, raw))
    if multiplier >= 0.95:
        tier = "FULL_SIZE"
    elif multiplier >= 0.65:
        tier = "REDUCED_SIZE"
    else:
        tier = "MINIMUM_SIZE"
    return WhaleConsensusSizing(
        multiplier=round(multiplier, 6),
        consensus_factor=consensus,
        freshness_factor=freshness,
        notional_factor=notional,
        tier=tier,
        reasons=(consensus_reason, freshness_reason, notional_reason),
    )


__all__ = ["FLOOR_MULTIPLIER", "WhaleConsensusSizing", "compute_whale_consensus_sizing"]
