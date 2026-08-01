"""[COPY-VAULT lot2 #38] GAP DETECTOR BASÉ SUR POSITION : si les fills reçus ne suffisent pas à EXPLIQUER la
nouvelle position du leader (position_après ≠ position_avant + somme des fills), on déclare un GAP — MÊME sans erreur
réseau visible. Un fill manqué se voit à l'incohérence de position, pas seulement à une déconnexion. Pur, 0 réseau.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_TOL = 1e-6


def detecter(position_avant: Any, fills_signes: Iterable[Any], position_apres: Any) -> dict[str, Any]:
    """GAP si position_avant + Σ fills ≠ position_apres (à tolérance près). Données invalides → GAP présumé."""
    if not all(isinstance(x, (int, float)) for x in (position_avant, position_apres)):
        return {"gap": True, "raison": "POSITION_INVALIDE"}
    somme = 0.0
    for f in fills_signes:
        if not isinstance(f, (int, float)):
            return {"gap": True, "raison": "FILL_INVALIDE"}
        somme += float(f)
    attendu = float(position_avant) + somme
    ecart = attendu - float(position_apres)
    if abs(ecart) > _TOL:
        return {"gap": True, "ecart": round(ecart, 8), "raison": "FILLS_N_EXPLIQUENT_PAS_LA_POSITION"}
    return {"gap": False, "raison": "POSITION_EXPLIQUEE_PAR_LES_FILLS"}


__all__ = ["detecter"]
