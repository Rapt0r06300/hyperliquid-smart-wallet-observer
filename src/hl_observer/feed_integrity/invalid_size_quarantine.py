"""[DATA pépite 269] INVALID-SIZE QUARANTINE : un niveau de carnet à taille négative, NaN, inf, ou à un prix
impossible (≤ 0, NaN, inf) invalide IMMÉDIATEMENT l'update — on ne l'applique pas au carnet, on ne le
« clippe » pas à zéro en douce. Une taille nulle est admise UNIQUEMENT comme suppression explicite de niveau.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

VALIDE = "VALIDE"
INVALIDE = "INVALIDE"
SUPPRESSION = "SUPPRESSION"


def _fini(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def valider_niveau(prix: Any, taille: Any, *, taille_max: float | None = None) -> dict[str, Any]:
    """Prix doit être fini et > 0 ; taille doit être finie et ≥ 0. taille == 0 → SUPPRESSION explicite.
    taille > taille_max (si fourni) → INVALIDE (taille impossible). Tout écart → INVALIDE (quarantaine)."""
    if not _fini(prix) or prix <= 0:
        return {"etat": INVALIDE, "raison": "PRIX_IMPOSSIBLE"}
    if not _fini(taille) or taille < 0:
        return {"etat": INVALIDE, "raison": "TAILLE_IMPOSSIBLE"}
    if taille_max is not None and _fini(taille_max) and taille > taille_max:
        return {"etat": INVALIDE, "raison": "TAILLE_SUPERIEURE_MAX"}
    if taille == 0:
        return {"etat": SUPPRESSION, "prix": float(prix)}
    return {"etat": VALIDE, "prix": float(prix), "taille": float(taille)}


__all__ = ["valider_niveau", "VALIDE", "INVALIDE", "SUPPRESSION"]
