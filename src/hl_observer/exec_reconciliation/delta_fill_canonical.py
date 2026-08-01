"""[EXEC pépite 203] DELTA-FILL CANONICAL : transformer SYSTÉMATIQUEMENT les rapports CUMULATIFS de fill en
new_fill = cumulative_new − cumulative_previous AVANT toute comptabilité. Beaucoup de venues envoient un cumulé
(« total rempli = 3.0 ») et non l'incrément ; compter le cumulé comme un nouveau fill dédoublerait la position. On
canonicalise en delta. Un cumulé qui RECULE (< précédent) est une anomalie signalée, jamais un fill négatif appliqué.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def delta_fill(cumulative_new: Any, cumulative_previous: Any) -> dict[str, Any]:
    """new_fill = cumulative_new − cumulative_previous. Un cumulé qui recule (new < previous) → anomalie
    (cum_filled ne doit jamais diminuer) : new_fill non appliqué. Données invalides → UNMEASURABLE."""
    if not all(isinstance(x, (int, float)) for x in (cumulative_new, cumulative_previous)) \
            or float(cumulative_new) < 0 or float(cumulative_previous) < 0:
        return {"new_fill": UNMEASURABLE, "raison": "CUMUL_INVALIDE"}
    if float(cumulative_new) < float(cumulative_previous) - 1e-12:
        return {"new_fill": UNMEASURABLE, "anomalie": True, "raison": "CUMUL_EN_RECUL"}
    return {"new_fill": round(float(cumulative_new) - float(cumulative_previous), 12), "anomalie": False}


__all__ = ["delta_fill", "UNMEASURABLE"]
