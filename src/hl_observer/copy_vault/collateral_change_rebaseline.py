"""[COPY-VAULT lot2 #58] REBASELINE APRÈS CHANGEMENT DE COLLATÉRAL : après un dépôt/retrait détecté (#57), il faut
REBASELINE l'equity de référence AVANT de calculer de nouvelles tailles copiées. Sinon on continuerait de
dimensionner avec l'ancien ratio equity, faussant toutes les tailles suivantes. Le rebaseline fixe la nouvelle
equity de référence. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def doit_rebaseline(depot_retrait_detecte: Any) -> dict[str, Any]:
    """Un dépôt/retrait détecté impose un rebaseline avant tout nouveau sizing."""
    if bool(depot_retrait_detecte):
        return {"rebaseline": True, "bloquer_sizing_avant": True, "raison": "CHANGEMENT_COLLATERAL"}
    return {"rebaseline": False, "raison": "PAS_DE_CHANGEMENT"}


def nouvelle_reference(equity_apres_changement: Any) -> Any:
    """Fixe la nouvelle equity de référence après rebaseline. Equity invalide → UNMEASURABLE (pas de sizing tant
    que la référence n'est pas fixée)."""
    if not isinstance(equity_apres_changement, (int, float)) or float(equity_apres_changement) <= 0:
        return UNMEASURABLE
    return round(float(equity_apres_changement), 8)


__all__ = ["doit_rebaseline", "nouvelle_reference", "UNMEASURABLE"]
