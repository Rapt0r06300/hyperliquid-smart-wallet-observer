"""CLASSEMENT du carry — choisir les MEILLEURS coins, pas seulement les éligibles.

Le scanner (`carry_scanner`) répond oui/non par coin. Mais « moins de trades, beaucoup plus propres »
demande un pas de plus : **ranger** la shortlist et n'ouvrir que le haut du panier. On classe par
**carry net prédit par heure** = funding prédit (EWMA, `funding_prediction.predire`) − coûts amortis,
et on **jette** tout coin non soutenable (funding sous les coûts) ou menacé d'inversion
(`carry_soutenable`). Deny-by-default : historique trop court → écarté (on ne devine pas).

Module PUR. Il PROPOSE un ordre de priorité ; **le noyau dispose** (chaque entrée repasse par
`noyau_unique.decider()` : frais réels, prix exécutables, VPIN, profondeur). Un classement n'est pas
un ordre.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from hl_observer.funding.funding_prediction import carry_soutenable, predire


@dataclass(frozen=True, slots=True)
class CarryClasse:
    coin: str
    funding_predit_bps_h: float
    net_bps_h: float          # funding prédit − coûts amortis (> 0 pour tout coin classé)
    rang: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin,
            "funding_predit_bps_h": round(self.funding_predit_bps_h, 4),
            "net_bps_h": round(self.net_bps_h, 4),
            "rang": self.rang,
            "real_execution": False,
        }


def classer(
    funding_par_coin: Mapping[str, Sequence[float]],
    *,
    cout_amorti_bps_h: float,
) -> list[CarryClasse]:
    """Classe les coins par carry NET prédit (bps/h) décroissant. N'inclut que les soutenables.

    `cout_amorti_bps_h` : les coûts (≈ 23 bps sur 4 exécutions) ramenés à l'heure de détention.
    Un coin non soutenable (funding < coûts) ou menacé d'inversion est **absent** du résultat.
    """
    cands: list[tuple[str, float, float]] = []
    for coin, f in funding_par_coin.items():
        p = predire(f)
        if p is None:                                    # histo trop court → deny-by-default
            continue
        if not carry_soutenable(f, cout_amorti_bps_h=cout_amorti_bps_h):
            continue                                     # None (insuffisant) ou False → écarté
        cands.append((coin, float(p), float(p) - float(cout_amorti_bps_h)))

    cands.sort(key=lambda x: x[2], reverse=True)         # meilleur carry NET d'abord
    return [
        CarryClasse(coin=c, funding_predit_bps_h=p, net_bps_h=net, rang=i + 1)
        for i, (c, p, net) in enumerate(cands)
    ]


def meilleur(
    funding_par_coin: Mapping[str, Sequence[float]],
    *,
    cout_amorti_bps_h: float,
) -> CarryClasse | None:
    """Le coin de carry le plus prometteur (net prédit le plus haut), ou `None` si aucun soutenable."""
    cl = classer(funding_par_coin, cout_amorti_bps_h=cout_amorti_bps_h)
    return cl[0] if cl else None


__all__ = ["CarryClasse", "classer", "meilleur"]
