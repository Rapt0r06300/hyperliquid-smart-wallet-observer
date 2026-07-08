"""Contrôleur d'admission par le board unifié (refonte sélection, sûr + réconcilié).

Principe: chaque chemin de trade (copy, funding, distilled) doit CLEARER la même
barre que le board unifié avant d'ouvrir — il entre ainsi en compétition avec TOUTES
les stratégies pour les slots, au lieu de remplir des silos indépendants.

La barre = le power score de la Kᵉ meilleure opportunité du board (le slot marginal).
S'il reste de la place (moins de K opportunités), la barre = 0 (tout candidat à power
positif est admis). Un candidat calcule son power via le MÊME scorer (opportunity_ranker,
zéro duplication) et est admis si power ≥ barre.

Sûr par construction: l'admission se fait AVANT soumission → un refus = pas d'ouverture
→ equity inchangée → aucune désync du ledger. Flag-gated en amont. Pur, paper-only.
"""

from __future__ import annotations

from typing import Any

from hl_observer.signals.opportunity_ranker import OpportunityInput, RankerConfig, power_score


def _g(obj: Any, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def admission_floor_power(board: list, *, max_slots: int) -> float:
    """Barre de power pour être admis. 0 s'il reste des slots ; sinon le power du
    slot marginal (Kᵉ meilleur). max_slots ≤ 0 → barre 0 (pas de contrainte de slot)."""
    slots = int(max_slots)
    if slots <= 0 or not board or len(board) < slots:
        return 0.0
    powers = sorted((float(_g(e, "power_score", 0.0) or 0.0) for e in board), reverse=True)
    return powers[slots - 1]


def candidate_power(
    *, coin: str, side: str, net_edge_bps: float, signal_age_ms: int,
    consensus_wallets: int = 1, liquidity_score: float = 0.5,
    leader_winrate: float | None = None, config: RankerConfig | None = None,
) -> float:
    """Power 0..100 d'un candidat via le scorer unifié (0 = plancher échoué)."""
    return power_score(
        OpportunityInput(
            coin=str(coin), side=str(side), net_edge_bps=float(net_edge_bps),
            signal_age_ms=int(signal_age_ms), consensus_wallets=int(consensus_wallets),
            liquidity_score=float(liquidity_score), leader_winrate=leader_winrate,
        ),
        config,
    )


def is_admitted(candidate_power_score: float, floor_power: float) -> bool:
    """Admis si le candidat clère la barre ET a un power strictement positif
    (power 0 = plancher dur échoué → jamais admis)."""
    cp = float(candidate_power_score)
    return cp > 0.0 and cp >= float(floor_power)


def admits_candidate(
    board: list, *, max_slots: int, coin: str, side: str, net_edge_bps: float,
    signal_age_ms: int, consensus_wallets: int = 1, liquidity_score: float = 0.5,
    leader_winrate: float | None = None, config: RankerConfig | None = None,
) -> dict:
    """Décision d'admission complète (pour un chemin de trade). Renvoie
    {admitted, candidate_power, floor_power}."""
    floor = admission_floor_power(board, max_slots=max_slots)
    cp = candidate_power(
        coin=coin, side=side, net_edge_bps=net_edge_bps, signal_age_ms=signal_age_ms,
        consensus_wallets=consensus_wallets, liquidity_score=liquidity_score,
        leader_winrate=leader_winrate, config=config,
    )
    return {"admitted": is_admitted(cp, floor), "candidate_power": round(cp, 4), "floor_power": round(floor, 4)}


def compute_admission_floor_for_fusion(
    *, funding_signals=(), triangular=(), distilled_opportunities=(),
    funding_rates_bps_by_coin=None, now_ms=0, max_slots=None, env=None,
):
    """Barre d'admission pour le fusion runtime, FLAG-GATED
    (HYPERSMART_GRINDER_UNIFIED_SELECTION). None si le flag est off -> aucune
    contrainte (comportement inchange). Sinon: construit le board unifie depuis les
    candidats et renvoie le power du slot marginal."""
    import os as _os

    e = env if env is not None else _os.environ
    if str(e.get('HYPERSMART_GRINDER_UNIFIED_SELECTION', '0')).strip().lower() not in {'1', 'true', 'yes', 'on'}:
        return None
    try:
        from hl_observer.integration.opportunity_board_adapter import board_from_fusion_result
        slots_raw = e.get('HYPERSMART_GRINDER_MAX_NEW_ENTRIES')
        slots = int(slots_raw) if slots_raw not in (None, '') else (int(max_slots) if max_slots else 12)

        class _R:
            pass
        r = _R()
        r.funding_signals = list(funding_signals or ())
        r.triangular_opportunities = list(triangular or ())
        r.distilled_opportunity_report = type('D', (), {'opportunities': list(distilled_opportunities or ())})()
        board = board_from_fusion_result(r, now_ms=int(now_ms), limit=max(64, slots), funding_rates_bps_by_coin=funding_rates_bps_by_coin)
        return admission_floor_power(board, max_slots=slots)
    except Exception:
        return None


__all__ = ["admission_floor_power", "candidate_power", "is_admitted", "admits_candidate", "compute_admission_floor_for_fusion"]
