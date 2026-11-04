"""[COPY-VAULT #71] AMBIGUOUS-ACTION DENY : un fill dont l'action (OPEN / ADD / REDUCE / CLOSE) ne peut pas être
déterminée proprement ne doit créer AUCUNE nouvelle exposition. Dans le doute, on autorise au plus une réduction,
jamais une ouverture : une action mal comprise qui augmente le risque est le pire cas. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

_CLAIR_AUGMENTE = ("OPEN", "ADD")
_CLAIR_REDUIT = ("REDUCE", "CLOSE")


def _confidence_is_valid(value: Any, threshold: Any) -> bool:
    """Accept only a finite probability and a finite threshold in [0, 1]."""

    if isinstance(value, bool) or isinstance(threshold, bool):
        return False
    try:
        confidence = float(value)
        minimum = float(threshold)
    except (TypeError, ValueError, OverflowError):
        return False
    return (
        math.isfinite(confidence)
        and math.isfinite(minimum)
        and 0.0 <= confidence <= 1.0
        and 0.0 <= minimum <= 1.0
        and confidence >= minimum
    )


def decision(action_determinee: Any, *, confiance: Any = None, seuil_confiance: float = 0.7) -> dict[str, Any]:
    """Autorise une nouvelle exposition SEULEMENT si l'action est clairement OPEN/ADD ET la confiance ≥ seuil.
    Ambigu, inconnu ou peu confiant → pas de nouvelle exposition (réduction éventuellement tolérée)."""
    a = str(action_determinee).upper()
    conf_ok = _confidence_is_valid(confiance, seuil_confiance)
    if a in _CLAIR_REDUIT:
        return {"nouvelle_exposition": False, "autorise_reduction": True, "raison": "REDUCTION"}
    if a in _CLAIR_AUGMENTE and conf_ok:
        return {"nouvelle_exposition": True, "autorise_reduction": True, "raison": "ACTION_CLAIRE"}
    return {"nouvelle_exposition": False, "autorise_reduction": True,
            "raison": ("CONFIANCE_INSUFFISANTE" if a in _CLAIR_AUGMENTE else "ACTION_AMBIGUE")}


def decision_with_pre_state(action_determinee: Any, *, pre_state: Any, confiance: Any = None,
                            seuil_confiance: float = 0.7) -> dict[str, Any]:
    """Refuse any action when the source pre-state is absent or unknown."""

    state = str(pre_state or "").upper()
    if state not in {"FLAT", "OPEN", "LONG", "SHORT"}:
        return {"status": "PROVEN", "nouvelle_exposition": False, "autorise_reduction": False,
                "raison": "PRE_STATE_MISSING_OR_UNKNOWN", "paper_read_only": True}
    result = decision(action_determinee, confiance=confiance, seuil_confiance=seuil_confiance)
    return {"status": "PROVEN", **result, "pre_state": state, "paper_read_only": True}


__all__ = ["decision", "decision_with_pre_state"]
