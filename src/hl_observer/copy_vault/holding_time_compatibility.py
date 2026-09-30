"""[COPY-VAULT pépite 286] HOLDING-TIME COMPATIBILITY : une stratégie qui tient une position 3 secondes ne se
copie pas avec les mêmes exigences qu'un vault qui tient plusieurs heures. Si notre latence de copie est du même
ordre que la durée de détention du leader, la position est déjà refermée quand on entre : incompatible. On
mesure le rapport latence/holding pour graduer la compatibilité. Durées invalides → UNMEASURABLE. Pur, 0 réseau,
0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

COMPATIBLE = "COMPATIBLE"
DEGRADE = "DEGRADE"
INCOMPATIBLE = "INCOMPATIBLE"
UNMEASURABLE = "UNMEASURABLE"


def evaluer(duree_holding_s: Any, *, latence_copie_s: float = 1.0,
            ratio_degrade: float = 0.2) -> dict[str, Any]:
    """ratio = latence_copie / duree_holding. ratio ≥ 1 → INCOMPATIBLE (position déjà fermée). ratio ≥
    ratio_degrade → DEGRADE (on n'attrape qu'une fraction du mouvement). Sinon COMPATIBLE. Durée ≤ 0 /
    invalide → UNMEASURABLE."""
    if not (isinstance(duree_holding_s, (int, float)) and not isinstance(duree_holding_s, bool)
            and math.isfinite(duree_holding_s)) or duree_holding_s <= 0:
        return {"etat": UNMEASURABLE, "raison": "DUREE_INVALIDE"}
    ratio = float(latence_copie_s) / float(duree_holding_s)
    if ratio >= 1.0:
        etat = INCOMPATIBLE
    elif ratio >= ratio_degrade:
        etat = DEGRADE
    else:
        etat = COMPATIBLE
    return {"etat": etat, "ratio_latence_holding": round(ratio, 6)}


__all__ = ["evaluer", "COMPATIBLE", "DEGRADE", "INCOMPATIBLE", "UNMEASURABLE"]
