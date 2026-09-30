"""PRÉDICTION DU FUNDING — améliorer NOTRE seule piste positive (le carry).

Le carry delta-neutre encaisse le funding (long spot + short perp). Aujourd'hui le scanner juge sur
la **moyenne** des fundings récents. On peut faire mieux, sur deux axes :

1. **Prédire le prochain funding** (EWMA : le récent pèse plus que le vieux) → meilleur *timing
   d'entrée*.
2. **Détecter le risque d'INVERSION** : *le funding peut passer négatif — BERA (−0,83) et STABLE
   (−0,99) l'ont fait.* Un carry long qui voit son funding s'inverser **perd**. On le signale AVANT.

🔒 Deny-by-default : historique trop court → `None`. *On ne devine pas ; ne pas savoir n'est pas
une permission.* Ce module PROPOSE des signaux ; **le noyau dispose** (le scanner + PORTE 4 gardent
l'autorité sur les coûts). Module PUR (aucun réseau, aucun état).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

MIN_HIST = 8          # au moins 8 points horaires pour prétendre prédire quoi que ce soit
ALPHA_DEFAUT = 0.4    # poids du plus récent dans l'EWMA


def predire(fundings_horaires: Sequence[float], *, alpha: float = ALPHA_DEFAUT) -> float | None:
    """Prochain funding horaire (bps), estimé par moyenne exponentielle. `None` si trop peu d'histo."""
    xs = [float(x) for x in fundings_horaires if x is not None]
    if len(xs) < MIN_HIST:
        return None
    ewma = xs[0]
    for x in xs[1:]:
        ewma = alpha * x + (1.0 - alpha) * ewma
    return ewma


@dataclass(frozen=True)
class RisqueInversion:
    frac_negatifs: float   # fraction des points récents qui étaient négatifs
    tendance: float        # dernier − premier (sur la fenêtre) ; < 0 = ça glisse vers le négatif
    dernier: float         # dernier funding observé
    alerte: bool           # faut-il se méfier d'une inversion ?

    def as_dict(self) -> dict[str, Any]:
        return {
            "frac_negatifs": self.frac_negatifs,
            "tendance": self.tendance,
            "dernier": self.dernier,
            "alerte": self.alerte,
        }


def risque_inversion(
    fundings_horaires: Sequence[float],
    *,
    fenetre: int = MIN_HIST,
    seuil_frac_neg: float = 0.25,
) -> RisqueInversion | None:
    """Le funding menace-t-il de passer/rester négatif (mauvais pour un carry long) ? `None` si peu d'histo."""
    xs = [float(x) for x in fundings_horaires if x is not None]
    if len(xs) < fenetre:
        return None
    recents = xs[-fenetre:]
    frac_neg = sum(1 for x in recents if x < 0.0) / len(recents)
    tendance = recents[-1] - recents[0]
    # alerte si déjà souvent négatif, OU si ça baisse ET le dernier point est proche de zéro / négatif.
    alerte = (frac_neg >= seuil_frac_neg) or (tendance < 0.0 and recents[-1] <= 0.0)
    return RisqueInversion(
        frac_negatifs=frac_neg, tendance=tendance, dernier=recents[-1], alerte=alerte
    )


def carry_soutenable(
    fundings_horaires: Sequence[float],
    *,
    cout_amorti_bps_h: float,
) -> bool | None:
    """Le funding prédit couvre-t-il les coûts amortis ET n'est-il pas menacé d'inversion ?

    `cout_amorti_bps_h` = les coûts (≈ 23 bps / 4 exécutions) ramenés à l'heure de détention.
    Renvoie `None` si on ne peut pas trancher (historique insuffisant).
    """
    p = predire(fundings_horaires)
    if p is None:
        return None
    r = risque_inversion(fundings_horaires)
    if r is None:
        return None
    return (p > float(cout_amorti_bps_h)) and (not r.alerte)
