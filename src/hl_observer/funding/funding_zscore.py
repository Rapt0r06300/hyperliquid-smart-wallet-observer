"""A4 — FUNDING EN Z-SCORE : capter le PREMIUM quand il est anormalement haut, pas le plancher.

Un funding momentanément élevé vs SON PROPRE historique = un premium à capter MAINTENANT (il
reviendra à la normale). Le z-score mesure cet écart. Couche de TIMING, complémentaire d'A1 :
  * A1 (persistance) répond « est-ce SÛR ? » -> viabilité sur le funding conservateur.
  * A4 (z-score)     répond « est-ce le BON MOMENT ? » -> parmi les carrys viables, préférer ceux
    qui spikent, et signaler que le premium s'est évaporé (retour à la moyenne).

Pas contradictoire : on n'entre que des carrys A1-sûrs ; A4 ne fait que PRIORISER et TIMER.
Vérité des données : historique trop court -> non fiable (on ne devine pas). PAPER only.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev

MIN_POINTS = 24
SEUIL_SPIKE = 1.0       # z >= +1 : funding anormalement HAUT (premium présent -> bon moment d'entrer)
SEUIL_EVAPORE = -0.5    # z <= -0.5 : premium évaporé / funding sous sa norme (envisager la sortie)


@dataclass(frozen=True, slots=True)
class FundingZScore:
    coin: str
    n_points: int
    courant_bps_h: float
    moyenne_bps_h: float
    ecart_type_bps_h: float
    zscore: float
    regime: str          # "SPIKE" / "NORMAL" / "EVAPORE" / "NON_FIABLE"
    fiable: bool

    def as_dict(self) -> dict:
        return {
            "coin": self.coin, "n_points": self.n_points, "courant_bps_h": self.courant_bps_h,
            "moyenne_bps_h": self.moyenne_bps_h, "ecart_type_bps_h": self.ecart_type_bps_h,
            "zscore": self.zscore, "regime": self.regime, "fiable": self.fiable,
        }


def zscore_funding(coin: str, historique_bps_h, courant_bps_h=None, *,
                   min_points: int = MIN_POINTS) -> FundingZScore:
    """(courant − moyenne)/écart-type du funding. `courant` par défaut = dernier point de l'historique."""
    serie = [float(x) for x in (historique_bps_h or []) if isinstance(x, (int, float))]
    if len(serie) < int(min_points):
        cur = float(courant_bps_h) if isinstance(courant_bps_h, (int, float)) else 0.0
        return FundingZScore(str(coin).upper(), len(serie), round(cur, 6), 0.0, 0.0, 0.0,
                             "NON_FIABLE", False)
    mu = mean(serie)
    sd = pstdev(serie)
    cur = float(courant_bps_h) if isinstance(courant_bps_h, (int, float)) else float(serie[-1])
    z = (cur - mu) / sd if sd > 1e-9 else 0.0
    if z >= SEUIL_SPIKE:
        reg = "SPIKE"
    elif z <= SEUIL_EVAPORE:
        reg = "EVAPORE"
    else:
        reg = "NORMAL"
    return FundingZScore(str(coin).upper(), len(serie), round(cur, 6), round(mu, 6),
                         round(sd, 6), round(z, 4), reg, True)


__all__ = ["MIN_POINTS", "SEUIL_SPIKE", "SEUIL_EVAPORE", "FundingZScore", "zscore_funding"]
