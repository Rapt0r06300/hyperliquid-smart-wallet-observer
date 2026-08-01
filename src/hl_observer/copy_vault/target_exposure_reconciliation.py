"""[COPY-VAULT #78] TARGET-EXPOSURE RECONCILIATION : comparer RÉGULIÈREMENT l'exposition DÉSIRÉE (déduite des fills
du leader) à l'exposition paper réellement obtenue. Un écart persistant signale une réplication qui dérive
(fills manqués, arrondis, caps). On calcule l'ajustement à appliquer pour recoller à la cible. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def reconcilier(exposition_cible: Any, exposition_paper: Any, *, tolerance: float = 1e-6) -> dict[str, Any]:
    """Écart = cible − paper. |écart| ≤ tolérance → aligné. Sinon → ajustement à appliquer (delta signé).
    Donnée manquante → UNMEASURABLE (on ne devine pas l'écart)."""
    if not all(isinstance(x, (int, float)) for x in (exposition_cible, exposition_paper)):
        return {"aligne": False, "ajustement": UNMEASURABLE, "raison": "EXPOSITION_MANQUANTE"}
    ecart = float(exposition_cible) - float(exposition_paper)
    if abs(ecart) <= float(tolerance):
        return {"aligne": True, "ajustement": 0.0, "raison": "ALIGNE"}
    return {"aligne": False, "ajustement": round(ecart, 12),
            "sens": ("ACHAT" if ecart > 0 else "VENTE"), "raison": "DERIVE_A_CORRIGER"}


__all__ = ["reconcilier", "UNMEASURABLE"]
