"""L5 — COUPE DE FRAÎCHEUR AVANT ENVOI : ne jamais agir sur une donnée périmée.

Juste AVANT d'émettre un intent, on revérifie l'âge du signal. Périmé -> NO_TRADE. C'est la
dernière barrière : entre la décision et l'envoi, le monde a pu bouger. Deny-by-default : âge
inconnu -> périmé. PAPER only.
"""
from __future__ import annotations

MAX_AGE_S_DEFAUT = 120.0


def frais_pour_envoi(age_signal_s: float | None, *, max_age_s: float = MAX_AGE_S_DEFAUT) -> bool:
    """True si le signal est assez frais pour être envoyé. None/négatif/trop vieux -> False."""
    if age_signal_s is None:
        return False
    try:
        a = float(age_signal_s)
    except (TypeError, ValueError):
        return False
    return 0.0 <= a <= float(max_age_s)


__all__ = ["MAX_AGE_S_DEFAUT", "frais_pour_envoi"]
