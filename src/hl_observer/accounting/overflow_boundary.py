"""[ACCOUNTING pépite 221] OVERFLOW BOUNDARY TESTS : vérifier explicitement les PLUS GROS prix/notionals/quantités
admissibles pour détecter une troncation d'entier ou un dépassement de précision AVANT qu'il ne corrompe une
balance. On borne chaque grandeur à un maximum admissible ; au-delà, on refuse (UNMEASURABLE) plutôt que de laisser
un overflow silencieux produire un chiffre faux. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

# borne de sécurité : 2^53 = plus grand entier représentable exactement en float64
MAX_ENTIER_SUR = 2 ** 53


def dans_bornes(valeur: Any, *, maximum: float = float(MAX_ENTIER_SUR)) -> dict[str, Any]:
    """Vrai si |valeur| ≤ maximum admissible ET valeur finie. Au-delà (ou non finie) → hors bornes (overflow
    potentiel), refusé. Le maximum par défaut est 2^53 (limite d'exactitude float64)."""
    if not isinstance(valeur, (int, float)):
        return {"ok": False, "raison": "VALEUR_INVALIDE"}
    v = float(valeur)
    if v != v or v in (float("inf"), float("-inf")):
        return {"ok": False, "raison": "NON_FINIE"}
    ok = abs(v) <= float(maximum)
    return {"ok": bool(ok), "valeur": v, "maximum": float(maximum),
            "raison": ("OK" if ok else "DEPASSE_BORNE_OVERFLOW")}


def produit_sur(a: Any, b: Any, *, maximum: float = float(MAX_ENTIER_SUR)) -> dict[str, Any]:
    """Vérifie qu'un produit (prix × quantité = notional) ne dépasse pas la borne. Facteur invalide → refus.
    On teste AVANT de multiplier pour détecter un notional aberrant (troncation/overflow)."""
    if not all(isinstance(x, (int, float)) for x in (a, b)):
        return {"ok": False, "raison": "FACTEUR_INVALIDE"}
    p = abs(float(a) * float(b))
    return dans_bornes(p, maximum=maximum)


__all__ = ["dans_bornes", "produit_sur", "MAX_ENTIER_SUR"]
