"""LE MODÈLE DE REJET D'ORDRE (idée `modele_de_rejet_d_ordre` de moisson-fini.md).

*L'exchange rejette les ordres quand il est **surchargé** — c'est-à-dire **QUAND ÇA BOUGE**. Or
c'est exactement là que nos **stops** doivent passer.* Un stop qui se fait rejeter en pleine
cascade = une perte **non bornée**. Personne dans le corpus ne le modélise (#15).

🔒 **Règle dure.** Un stop qui **peut** être rejeté n'est **pas** un stop. Quand la probabilité de
rejet dépasse le seuil, la sortie n'est **pas garantie** → le noyau doit traiter la position comme
telle (réduire la taille, ou `NO_TRADE`). *Ne pas pouvoir sortir n'est pas une permission d'entrer.*

Repère mesuré (déjà en mémoire) : `BadAloPx` = un post-only qui croiserait est **REJETÉ** (pas
exécuté en taker). Le rejet est donc un fait observable dans nos propres données.

Module PUR (aucun réseau, aucun état).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VOL_CALME_BPS = 20.0     # en-dessous : marché calme, rejet négligeable
VOL_CHAOS_BPS = 200.0    # au-dessus : cascade, rejet quasi certain
MAX_PROBA_STOP_FIABLE = 0.20   # au-delà, on ne considère PAS la sortie comme garantie


def proba_rejet(
    volatilite_bps: float,
    *,
    vol_calme: float = VOL_CALME_BPS,
    vol_chaos: float = VOL_CHAOS_BPS,
) -> float:
    """Probabilité qu'un ordre soit rejeté, croissante avec la volatilité (proxy de la charge).

    Interpolation linéaire bornée : ~0 en marché calme, → 1 en cascade. *Modèle simple et honnête,
    à calibrer ensuite sur nos rejets observés — mais déjà mieux que « le rejet n'existe pas ».*
    """
    v = float(volatilite_bps)
    if v <= vol_calme:
        return 0.0
    if v >= vol_chaos:
        return 1.0
    return (v - vol_calme) / (vol_chaos - vol_calme)


@dataclass(frozen=True)
class VerdictSortie:
    proba_rejet: float
    garantie: bool      # la sortie (stop) est-elle fiable ?

    def as_dict(self) -> dict[str, Any]:
        return {"proba_rejet": self.proba_rejet, "garantie": self.garantie}


def evaluer_sortie(
    volatilite_bps: float,
    *,
    max_proba: float = MAX_PROBA_STOP_FIABLE,
    vol_calme: float = VOL_CALME_BPS,
    vol_chaos: float = VOL_CHAOS_BPS,
) -> VerdictSortie:
    """Un stop est-il fiable dans ces conditions ? *Sinon la sortie n'est pas garantie.*"""
    p = proba_rejet(volatilite_bps, vol_calme=vol_calme, vol_chaos=vol_chaos)
    return VerdictSortie(proba_rejet=p, garantie=(p <= max_proba))
