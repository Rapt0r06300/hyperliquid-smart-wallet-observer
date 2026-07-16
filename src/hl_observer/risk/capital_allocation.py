"""ALLOCATION DE CAPITAL entre stratégies — répartir SANS se concentrer, SANS payer une non-piste.

Quand plusieurs pistes coexistent (carry delta-neutre, liquidations, …), il faut décider combien de
capital va à chacune. La discipline du projet dicte les règles :

- 🔒 **Deny-by-default** : une stratégie dont l'edge NET (après coûts) est ≤ 0 reçoit **0**. On ne
  paie jamais une piste qui perd « pour voir ».
- ⚖️ **Edge par unité de risque** : le poids brut ∝ edge_net / risque (un Kelly fractionné prudent).
  Un gros edge très volatil ne mérite pas tout le capital.
- 🧱 **Plafond de concentration** : aucune stratégie ne dépasse `frac_max_par_strat`. Une piste qui
  meurt ne doit pas emporter le book.
- 🪙 **Le cash est une position légitime** : on n'investit pas 100 % de force. Ce qui n'est pas
  alloué **reste en cash** — et le cash est notre benchmark (une piste doit battre le cash, sinon
  elle est dominée).

Module PUR (aucun réseau, aucun état). Une allocation n'est pas un ordre — c'est le noyau qui,
ensuite, décide de chaque entrée réelle (paper) via ses propres portes.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

FRAC_MAX_PAR_STRAT_DEFAUT = 0.5     # aucune piste ne prend plus de la moitié du capital
EDGE_MIN_BPS_DEFAUT = 0.0           # deny-by-default : edge net ≤ 0 → 0 capital


@dataclass(frozen=True, slots=True)
class Strategie:
    nom: str
    edge_net_bps: float             # APRÈS coûts (vient du noyau d'edge / des mesures)
    risque: float                   # volatilité des rendements (> 0) ; plus haut = moins de poids
    plafond_frac: float = 1.0       # plafond propre à la stratégie (≤ frac_max global)


@dataclass(frozen=True, slots=True)
class Allocation:
    poids: dict[str, float]         # fraction du capital par stratégie (somme ≤ 1)
    cash_frac: float
    motif: str
    ecartees: tuple[str, ...] = field(default_factory=tuple)   # noms mis à 0 (edge ≤ 0 / risque ≤ 0)

    def montants(self, capital_usd: float) -> dict[str, float]:
        return {nom: round(w * float(capital_usd), 6) for nom, w in self.poids.items()}

    def as_dict(self) -> dict[str, Any]:
        return {
            "poids": dict(self.poids),
            "cash_frac": round(self.cash_frac, 6),
            "motif": self.motif,
            "ecartees": list(self.ecartees),
            "real_execution": False,
        }


def allouer(
    strategies: Sequence[Strategie],
    *,
    frac_max_par_strat: float = FRAC_MAX_PAR_STRAT_DEFAUT,
    edge_min_bps: float = EDGE_MIN_BPS_DEFAUT,
) -> Allocation:
    """Répartit une fraction de 1.0 entre les stratégies éligibles ; le reste est du cash.

    Éligible = edge_net_bps > `edge_min_bps` ET risque > 0. Poids ∝ edge/risque, plafonné.
    """
    eligibles: list[Strategie] = []
    ecartees: list[str] = []
    for s in strategies:
        if s.edge_net_bps > float(edge_min_bps) and s.risque > 0.0:
            eligibles.append(s)
        else:
            ecartees.append(s.nom)

    if not eligibles:
        return Allocation(
            poids={}, cash_frac=1.0,
            motif="AUCUNE_PISTE_A_EDGE_NET_POSITIF_TOUT_EN_CASH",
            ecartees=tuple(ecartees),
        )

    scores = {s.nom: (s.edge_net_bps / s.risque) for s in eligibles}
    total = sum(scores.values())

    poids: dict[str, float] = {}
    for s in eligibles:
        brut = scores[s.nom] / total                       # part de l'edge/risque total
        plafond = min(float(frac_max_par_strat), float(s.plafond_frac))
        poids[s.nom] = min(brut, plafond)                  # on plafonne, on ne re-force pas à 1

    investi = sum(poids.values())
    cash = max(0.0, 1.0 - investi)
    return Allocation(
        poids=poids, cash_frac=cash,
        motif="ALLOUE_PAR_EDGE_SUR_RISQUE_PLAFONNE",
        ecartees=tuple(ecartees),
    )


__all__ = [
    "EDGE_MIN_BPS_DEFAUT", "FRAC_MAX_PAR_STRAT_DEFAUT",
    "Allocation", "Strategie", "allouer",
]
