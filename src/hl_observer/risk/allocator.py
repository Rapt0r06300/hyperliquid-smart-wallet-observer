"""N1 + N2 + N3 — ALLOCATION portefeuille : inverse-vol, rebalancement cost-aware, capacité.

N1 : poids ∝ 1/vol (risk-parity simplifié) — égalise la contribution au risque, pas le capital.
N2 : ne rebalancer que si l'écart de poids dépasse une BANDE (sinon le coût de transaction mange le
gain). N3 : capacité = combien de capital une stratégie absorbe avant que l'impact tue l'edge.
PUR. Deny-by-default. PAPER only.
"""
from __future__ import annotations

from typing import Mapping


def poids_inverse_vol(vols_par_actif: Mapping[str, float]) -> dict[str, float]:
    """Poids ∝ 1/vol, normalisés à somme 1. Vol <= 0 -> exclu (risque non mesurable)."""
    inv = {a: 1.0 / float(v) for a, v in (vols_par_actif or {}).items() if float(v) > 0}
    s = sum(inv.values())
    return {a: w / s for a, w in inv.items()} if s > 0 else {}


def rebalancement_necessaire(poids_actuels: Mapping[str, float], poids_cibles: Mapping[str, float], *,
                             bande: float = 0.05) -> bool:
    """True si un poids s'écarte de sa cible de plus que `bande` (sinon on ne churne pas)."""
    cles = set(poids_actuels or {}) | set(poids_cibles or {})
    return any(abs(float((poids_actuels or {}).get(c, 0.0)) - float((poids_cibles or {}).get(c, 0.0)))
               > float(bande) for c in cles)


def capacite_max_usd(profondeur_usd: float, *, impact_max_frac: float = 0.02,
                     securite: float = 5.0) -> float:
    """Capital max déployable = profondeur × impact_max / sécurité. Au-delà, l'impact tue l'edge."""
    return max(0.0, float(profondeur_usd) * float(impact_max_frac) / max(1.0, float(securite)))


__all__ = ["poids_inverse_vol", "rebalancement_necessaire", "capacite_max_usd"]
