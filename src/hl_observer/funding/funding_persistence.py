"""A1 — PERSISTANCE DU FUNDING : distinguer le plancher permanent du premium transitoire.

Le funding d'un perp = plancher protocolaire (permanent, ~0,125 bps/h, payé par les longs aux
shorts par construction) + premium (transitoire, décroît). Entrer un carry sur un premium ÉLEVÉ
mais fugace est un piège : il se retourne AVANT le break-even, et on a payé l'entrée pour rien.

Ce module estime, à partir de l'historique RÉEL (fundingHistory), le funding sur lequel on peut
VRAIMENT compter — une estimation CONSERVATRICE, résistante aux spikes. Le carry doit décider sur
ce funding persistant, pas sur le snapshot chanceux du moment.

Vérité des données : l'historique doit être MESURÉ. Série vide/trop courte -> non fiable (on
n'invente pas un funding). PAPER only : aucun ordre, aucune signature.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

# Source de vérité unique du plancher (partagée avec delta_neutral_carry).
from hl_observer.funding.delta_neutral_carry import PLANCHER_PROTOCOLAIRE_BPS_H

MIN_POINTS = 24                 # au moins 24 h d'historique horaire pour juger
QUANTILE_PRUDENT = 0.25         # on retient le premium tenu ~75 % du temps (bas = conservateur)


@dataclass(frozen=True, slots=True)
class FundingPersistant:
    coin: str
    n_points: int
    funding_median_bps_h: float
    premium_persistant_bps_h: float     # premium sur lequel on peut compter (quantile bas des premiums)
    funding_persistant_bps_h: float     # plancher + premium persistant = CE QU'ON UTILISE pour décider
    part_du_temps_au_dessus_plancher: float   # fraction du temps où funding > plancher (fiabilité)
    volatilite_bps_h: float             # écart-type du funding (instabilité)
    fiable: bool
    motif: str = ""

    def as_dict(self) -> dict:
        return {
            "coin": self.coin, "n_points": self.n_points,
            "funding_median_bps_h": self.funding_median_bps_h,
            "premium_persistant_bps_h": self.premium_persistant_bps_h,
            "funding_persistant_bps_h": self.funding_persistant_bps_h,
            "part_du_temps_au_dessus_plancher": self.part_du_temps_au_dessus_plancher,
            "volatilite_bps_h": self.volatilite_bps_h,
            "fiable": self.fiable, "motif": self.motif,
        }


def _quantile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    i = q * (len(s) - 1)
    lo = int(i)
    frac = i - lo
    if lo + 1 < len(s):
        return s[lo] * (1.0 - frac) + s[lo + 1] * frac
    return s[lo]


def estimer_persistance(coin: str, historique_bps_h, *,
                        plancher: float = PLANCHER_PROTOCOLAIRE_BPS_H,
                        min_points: int = MIN_POINTS,
                        quantile_prudent: float = QUANTILE_PRUDENT) -> FundingPersistant:
    """Historique (funding bps/h, du + ancien au + récent) -> estimation conservatrice du funding
    persistant. On ne garde du premium que ce qui TIENT (quantile bas), jamais le pic."""
    serie = [float(x) for x in (historique_bps_h or []) if isinstance(x, (int, float))]
    if len(serie) < int(min_points):
        return FundingPersistant(str(coin).upper(), len(serie), 0.0, 0.0, 0.0, 0.0, 0.0,
                                 False, "HISTORIQUE_INSUFFISANT")
    med = median(serie)
    premiums = [max(0.0, f - plancher) for f in serie]
    premium_pers = max(0.0, _quantile(premiums, quantile_prudent))
    funding_pers = plancher + premium_pers
    part_pos = sum(1 for f in serie if f > plancher) / len(serie)
    moy = sum(serie) / len(serie)
    vol = (sum((f - moy) ** 2 for f in serie) / len(serie)) ** 0.5
    return FundingPersistant(str(coin).upper(), len(serie), round(med, 6),
                             round(premium_pers, 6), round(funding_pers, 6),
                             round(part_pos, 4), round(vol, 6), True, "OK")


def couvre_cout(fp: FundingPersistant, cout_entree_bps: float, horizon_h: float) -> bool:
    """Le funding PERSISTANT couvre-t-il le coût d'entrée dans l'horizon ? (break-even prudent).
    Non fiable -> False (deny-by-default : pas d'historique = pas de décision)."""
    if not fp.fiable:
        return False
    return fp.funding_persistant_bps_h * float(horizon_h) >= float(cout_entree_bps)


__all__ = ["PLANCHER_PROTOCOLAIRE_BPS_H", "MIN_POINTS", "QUANTILE_PRUDENT",
           "FundingPersistant", "estimer_persistance", "couvre_cout"]
