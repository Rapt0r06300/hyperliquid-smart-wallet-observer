"""[COPY-VAULT #56] POST-ROUNDING NOTIONAL CHECK : après avoir arrondi la taille copiée (au lot/tick), RE-vérifier
le notional minimum exécutable. L'arrondi vers le bas peut faire tomber une petite copie sous le minimum de la
venue → l'ordre serait non exécutable. On valide APRÈS arrondi, pas avant. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def verifier(taille_arrondie: Any, prix: Any, *, min_notional: float) -> dict[str, Any]:
    """OK seulement si taille_arrondie × prix ≥ min_notional. Entrées invalides → refus (jamais supposé OK)."""
    if not all(isinstance(x, (int, float)) for x in (taille_arrondie, prix)):
        return {"ok": False, "notional": None, "raison": "ENTREE_INVALIDE"}
    notional = abs(float(taille_arrondie)) * float(prix)
    ok = notional >= float(min_notional)
    return {"ok": bool(ok), "notional": round(notional, 8), "min_notional": float(min_notional),
            "raison": ("OK" if ok else "SOUS_MIN_APRES_ARRONDI")}


__all__ = ["verifier"]
