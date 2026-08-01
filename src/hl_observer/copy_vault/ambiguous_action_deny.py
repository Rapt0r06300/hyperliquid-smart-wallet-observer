"""[COPY-VAULT #71] AMBIGUOUS-ACTION DENY : un fill dont l'action (OPEN / ADD / REDUCE / CLOSE) ne peut pas être
déterminée proprement ne doit créer AUCUNE nouvelle exposition. Dans le doute, on autorise au plus une réduction,
jamais une ouverture : une action mal comprise qui augmente le risque est le pire cas. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

_CLAIR_AUGMENTE = ("OPEN", "ADD")
_CLAIR_REDUIT = ("REDUCE", "CLOSE")


def decision(action_determinee: Any, *, confiance: Any = None, seuil_confiance: float = 0.7) -> dict[str, Any]:
    """Autorise une nouvelle exposition SEULEMENT si l'action est clairement OPEN/ADD ET la confiance ≥ seuil.
    Ambigu, inconnu ou peu confiant → pas de nouvelle exposition (réduction éventuellement tolérée)."""
    a = str(action_determinee).upper()
    conf_ok = isinstance(confiance, (int, float)) and float(confiance) >= float(seuil_confiance)
    if a in _CLAIR_REDUIT:
        return {"nouvelle_exposition": False, "autorise_reduction": True, "raison": "REDUCTION"}
    if a in _CLAIR_AUGMENTE and conf_ok:
        return {"nouvelle_exposition": True, "autorise_reduction": True, "raison": "ACTION_CLAIRE"}
    return {"nouvelle_exposition": False, "autorise_reduction": True,
            "raison": ("CONFIANCE_INSUFFISANTE" if a in _CLAIR_AUGMENTE else "ACTION_AMBIGUE")}


__all__ = ["decision"]
