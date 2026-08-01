"""[COPY-VAULT #55] LEADER LEVERAGE CEILING : ne pas reproduire mécaniquement un levier excessif du leader. Le
notional copié est borné par levier_max × notre_equity ; si le leader est à 20× et notre plafond est 5×, on ne
copie que jusqu'à 5×. Copier un levier fou revient à hériter de son risque de liquidation. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def notional_admissible(notional_demande: Any, *, notre_equity: Any, levier_max: float = 5.0) -> dict[str, Any]:
    """Borne le notional copié à levier_max × notre_equity. Entrées invalides → UNMEASURABLE + refus."""
    if not all(isinstance(x, (int, float)) for x in (notional_demande, notre_equity)) or float(levier_max) <= 0:
        return {"notional": UNMEASURABLE, "refuse": True, "raison": "ENTREE_INVALIDE"}
    if float(notre_equity) <= 0:
        return {"notional": UNMEASURABLE, "refuse": True, "raison": "EQUITY_NON_POSITIVE"}
    plafond = float(levier_max) * float(notre_equity)
    demande = abs(float(notional_demande))
    capee = min(demande, plafond)
    levier_implicite = demande / float(notre_equity)
    return {"notional": round(capee, 8), "plafond_notional": round(plafond, 8),
            "levier_demande": round(levier_implicite, 4), "capee": bool(demande > plafond), "refuse": False}


__all__ = ["notional_admissible", "UNMEASURABLE"]
