"""[EXEC pépite 206] CONTINUOUS POSITION RECONCILIATION : comparer PÉRIODIQUEMENT la position CALCULÉE depuis nos
fills à la position REPORT AUTORITAIRE (venue), afin de détecter les fills MANQUÉS. Si notre somme de fills ne
correspond pas au report, il nous manque (ou on a en trop) un fill — divergence à réconcilier. On ne fait jamais
confiance à notre seul calcul local. Données invalides → divergence présumée. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def reconcilier(position_calculee: Any, position_report: Any, *, tolerance: float = 1e-6) -> dict[str, Any]:
    """Compare la position calculée depuis les fills au report autoritaire. Écart > tolérance → divergence
    (fill manqué probable), avec l'écart signé. Données invalides → divergence présumée (fail-closed)."""
    if not all(isinstance(x, (int, float)) for x in (position_calculee, position_report)):
        return {"coherent": False, "raison": "DONNEE_INVALIDE"}
    ecart = float(position_report) - float(position_calculee)
    if abs(ecart) > float(tolerance):
        return {"coherent": False, "ecart": round(ecart, 12),
                "sens": ("FILL_MANQUE" if ecart != 0 else "OK"),
                "raison": "POSITION_LOCALE_DIVERGE_DU_REPORT"}
    return {"coherent": True, "raison": "POSITION_RECONCILIEE"}


__all__ = ["reconcilier"]
