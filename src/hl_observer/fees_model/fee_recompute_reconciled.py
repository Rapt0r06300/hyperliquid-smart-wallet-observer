"""[ARB lot2 #20] FRAIS RECALCULÉS SUR LES FILLS RÉCONCILIÉS : les frais sont recalculés sur les fills RÉELLEMENT
récupérés par réconciliation (prix/quantité/rôle maker-taker effectifs), pas seulement estimés à l'intention
initiale. Un fill réconcilié peut différer de l'intention (prix, partiel, taker au lieu de maker) → frais réels
différents. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def commission(notional: Any, taux_bps: Any) -> Any:
    """Commission = notional × taux/1e4. Entrée invalide → UNMEASURABLE (jamais 0 supposé)."""
    if not all(isinstance(x, (int, float)) for x in (notional, taux_bps)):
        return UNMEASURABLE
    return round(abs(float(notional)) * float(taux_bps) / 1e4, 8)


def recomputer(fills: Iterable[Any]) -> dict[str, Any]:
    """Somme les commissions RÉELLES des fills réconciliés {prix, qte, taux_bps}. Un fill incalculable est
    compté comme non mesurable (le total devient UNMEASURABLE — on ne masque pas un frais inconnu par 0)."""
    total = 0.0
    n = 0
    for f in fills:
        prix, qte, taux = (f or {}).get("prix"), (f or {}).get("qte"), (f or {}).get("taux_bps")
        if not all(isinstance(x, (int, float)) for x in (prix, qte, taux)):
            return {"commission_totale": UNMEASURABLE, "raison": "FILL_INCALCULABLE", "n_traites": n}
        total += abs(float(prix) * float(qte)) * float(taux) / 1e4
        n += 1
    return {"commission_totale": round(total, 8), "n_fills": n, "source": "fills_reconcilies"}


__all__ = ["commission", "recomputer", "UNMEASURABLE"]
