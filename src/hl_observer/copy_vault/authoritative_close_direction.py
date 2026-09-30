"""[COPY-VAULT #65] AUTHORITATIVE CLOSE DIRECTION : pour FERMER/RÉDUIRE, la direction (BUY/SELL) est déterminée par
la position COURANTE du vault, pas par le sens supposé du signal. Fermer un long = VENTE ; fermer un short = ACHAT.
La position réelle fait autorité, exactement comme le copy-trader inspecté. Position nulle/inconnue → pas de
fermeture possible. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

ACHAT = "ACHAT"
VENTE = "VENTE"
_TOL = 1e-12


def direction_fermeture(position_courante: Any) -> dict[str, Any]:
    """Long (>0) → fermer par VENTE ; short (<0) → fermer par ACHAT. Position ~0 ou inconnue → RIEN_A_FERMER."""
    if not isinstance(position_courante, (int, float)):
        return {"direction": None, "raison": "POSITION_INCONNUE"}
    p = float(position_courante)
    if abs(p) <= _TOL:
        return {"direction": None, "raison": "RIEN_A_FERMER"}
    return {"direction": (VENTE if p > 0 else ACHAT), "cote": ("LONG" if p > 0 else "SHORT")}


def direction_reduction(position_courante: Any, quantite: Any) -> dict[str, Any]:
    """Direction d'une réduction de `quantite` : opposée au côté détenu, bornée à la taille détenue."""
    base = direction_fermeture(position_courante)
    if base["direction"] is None:
        return base
    if not isinstance(quantite, (int, float)) or float(quantite) <= 0:
        return {"direction": None, "raison": "QUANTITE_INVALIDE"}
    q = min(abs(float(quantite)), abs(float(position_courante)))
    return {"direction": base["direction"], "quantite": round(q, 12), "cote": base["cote"]}


__all__ = ["direction_fermeture", "direction_reduction", "ACHAT", "VENTE"]
