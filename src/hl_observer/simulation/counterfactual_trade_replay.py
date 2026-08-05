"""AUD-131 — replay CONTREFACTUEL automatique PAR TRADE.

Pour chaque trade paper (entree->sortie), on rejoue des ALTERNATIVES sur le MEME chemin de prix :
ne pas entrer (0), meilleure sortie possible, tenir jusqu'a la fin. On mesure le PnL de chaque
alternative vs le trade REEL -> regret. Read-only, paper (real_execution=False).
"""
from __future__ import annotations

from typing import Sequence


def _pnl(side: int, entree: float, sortie: float, notional: float) -> float:
    if float(entree) == 0.0:
        return 0.0
    return float(side) * (float(sortie) - float(entree)) / float(entree) * float(notional)


def replay_contrefactuel_trade(*, side: int, prix_entree: float, prix_sortie: float,
                               notional_usd: float, chemin_prix: Sequence[float]) -> dict:
    reel = _pnl(side, prix_entree, prix_sortie, notional_usd)
    chemin = [float(p) for p in chemin_prix] or [float(prix_sortie)]
    best_sortie = max(chemin) if side >= 0 else min(chemin)
    contrefactuels = {
        "ne_pas_entrer": 0.0,
        "meilleure_sortie": _pnl(side, prix_entree, best_sortie, notional_usd),
        "tenir_jusqu_a_la_fin": _pnl(side, prix_entree, chemin[-1], notional_usd),
    }
    meilleur_cf = max([reel] + list(contrefactuels.values()))
    return {"pnl_reel": round(reel, 8), "contrefactuels": {k: round(v, 8) for k, v in contrefactuels.items()},
            "regret": round(meilleur_cf - reel, 8), "real_execution": False}


__all__ = ["replay_contrefactuel_trade"]
