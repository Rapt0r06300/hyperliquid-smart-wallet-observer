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


def rebaseline_receipt(*, collateral_changed: Any, equity_after: Any) -> dict[str, Any]:
    """Require a new positive reference before subsequent sizing."""

    if type(collateral_changed) is not bool:
        return {"status": "UNMEASURABLE", "sizing_allowed": False, "reason": "CHANGE_FLAG_INVALID", "paper_read_only": True}
    reference = nouvelle_reference(equity_after) if collateral_changed else None
    ready = not collateral_changed or reference != UNMEASURABLE
    return {"status": "PROVEN", "sizing_allowed": ready, "reference": reference,
            "historical_returns_unchanged": True,
            "reason": "REBASELINE_READY" if ready else "REBASELINE_REQUIRED",
            "paper_read_only": True}


__all__ = ["doit_rebaseline", "nouvelle_reference", "rebaseline_receipt", "UNMEASURABLE"]
