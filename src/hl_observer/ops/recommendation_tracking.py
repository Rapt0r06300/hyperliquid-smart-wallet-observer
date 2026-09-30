"""AUD-143 — suivi AVANT/APRES des recommandations.

On enregistre la metrique AVANT une reco, puis APRES son application, et on calcule le DELTA + si
elle a REELLEMENT aide (selon le sens attendu). Read-only.
"""
from __future__ import annotations


def suivre_recommandation(*, avant: float, apres: float, sens: str = "hausse",
                          delta_attendu: float | None = None) -> dict:
    delta = round(float(apres) - float(avant), 8)
    a_aide = delta > 0 if sens == "hausse" else delta < 0
    objectif = None
    if delta_attendu is not None:
        objectif = (delta >= float(delta_attendu)) if sens == "hausse" else (delta <= -abs(float(delta_attendu)))
    return {"avant": float(avant), "apres": float(apres), "delta": delta, "sens": sens,
            "a_aide": bool(a_aide), "objectif_atteint": objectif}


__all__ = ["suivre_recommandation"]
