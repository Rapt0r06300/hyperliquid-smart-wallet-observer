"""A2 — Pipeline copy/leaders: shortlist filtrée + décision de sortie.

Compose les briques pures livrées: classification comportement (swing-only),
scoring par coin/PF net, anti faux-consensus, ExitEngine. Deux entrées:
  - build_copy_shortlist(): qui a-t-on le droit de copier, et avec quel poids;
  - decide_position_exit(): quand fermer une position ouverte.
Flag-gated. Pur, testé. Câblage = importer et appeler dans la découverte + exits.
"""

from __future__ import annotations

import os

from hl_observer.exits.exit_engine import decide_exit
from hl_observer.following.leader_behavior import classify_leader
from hl_observer.following.leader_scoring import (
    count_consensus_clusters, market_score_multiplier, profit_factor_net, shortlist_by_net_pf,
)


def _on(flag: str) -> bool:
    return str(os.getenv(flag, "0")).strip().lower() in {"1", "true", "yes", "on"}


def build_copy_shortlist(
    *,
    candidate_wallets: list[str],
    fills_by_wallet: dict[str, list[dict]],
    closed_trades: list[dict],
    min_pf: float = 1.0,
    min_trades: int = 5,
) -> dict:
    """Filtre les leaders copiables: swing-only + PF net > 1. Renvoie shortlist + rejets."""

    swing_only = _on("HYPERSMART_COPY_SWING_ONLY")
    pf_gate = _on("HYPERSMART_COPY_PF_SHORTLIST")

    behaviors = {w: classify_leader(w, fills_by_wallet.get(w, [])) for w in candidate_wallets}
    kept = []
    rejected = {}
    for w in candidate_wallets:
        b = behaviors[w]
        if swing_only and not b.copyable:
            rejected[w] = b.reason
            continue
        kept.append(w)

    if pf_gate and kept:
        shortlisted = set(shortlist_by_net_pf(closed_trades, kept, min_pf=min_pf, min_trades=min_trades))
        for w in list(kept):
            if w not in shortlisted:
                rejected[w] = "PF_NET_BELOW_MIN"
        kept = [w for w in kept if w in shortlisted]

    return {
        "shortlist": kept,
        "rejected": rejected,
        "behaviors": {w: behaviors[w].kind for w in candidate_wallets},
        "swing_only_applied": swing_only,
        "pf_gate_applied": pf_gate,
    }


def consensus_and_coin_score(*, votes: list[dict], wallet: str, coin: str, closed_trades: list[dict]) -> dict:
    """Vrai consensus (clusters, pas adresses) + multiplicateur par marché du leader."""
    clusters = count_consensus_clusters(votes)
    coin_mult = market_score_multiplier(closed_trades, wallet, coin) if _on("HYPERSMART_COPY_COIN_SCORING") else 1.0
    return {
        "consensus_clusters": clusters["consensus_clusters"],
        "raw_wallets": clusters["raw_wallets"],
        "coin_score_multiplier": coin_mult,
        "leader_pf": profit_factor_net(closed_trades, wallet)["profit_factor_net"],
    }


def decide_position_exit(**kw) -> dict:
    """Passe-plat vers l'ExitEngine, gated par HYPERSMART_EXIT_ENGINE (sinon HOLD)."""
    if not _on("HYPERSMART_EXIT_ENGINE"):
        return {"action": "HOLD", "fraction": 0.0, "reason": "EXIT_ENGINE_OFF"}
    d = decide_exit(**kw)
    return {"action": d.action, "fraction": d.fraction, "reason": d.reason}


__all__ = ["build_copy_shortlist", "consensus_and_coin_score", "decide_position_exit"]
