"""[ACCOUNTING pépite 220] FIXED-POINT CORE : les prix/quantités/cash CRITIQUES sont manipulés en entier scalé
(fixed-point) ou Decimal contrôlé, JAMAIS en float arbitraire. Les erreurs d'arrondi float s'accumulent et font
diverger le recalcul de balance (bug fixed-point corrigé récemment dans Nautilus). On convertit en unités entières
au scale de l'instrument et on n'additionne que des entiers. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def vers_unites(valeur: Any, *, scale: int) -> Any:
    """Convertit une valeur en ENTIER d'unités au `scale` donné (10^scale). Ex. scale=2 : 1.23 -> 123.
    Utilise Decimal (half-even) pour éviter le bruit binaire du float. Valeur invalide → UNMEASURABLE."""
    if not isinstance(valeur, (int, float, str)) or not isinstance(scale, int) or scale < 0:
        return UNMEASURABLE
    try:
        d = (Decimal(str(valeur)) * (Decimal(10) ** scale)).quantize(Decimal(1), rounding=ROUND_HALF_EVEN)
    except Exception:
        return UNMEASURABLE
    return int(d)


def depuis_unites(unites: Any, *, scale: int) -> Any:
    """Reconvertit un entier d'unités en valeur décimale exacte (Decimal). Entrée invalide → UNMEASURABLE."""
    if not isinstance(unites, int) or not isinstance(scale, int) or scale < 0:
        return UNMEASURABLE
    return Decimal(unites) / (Decimal(10) ** scale)


def somme_exacte(valeurs: Any, *, scale: int) -> Any:
    """Somme EXACTE en additionnant des entiers d'unités (pas de dérive float). Une valeur invalide → UNMEASURABLE."""
    total = 0
    for v in valeurs:
        u = vers_unites(v, scale=scale)
        if u == UNMEASURABLE:
            return UNMEASURABLE
        total += u
    return depuis_unites(total, scale=scale)


__all__ = ["vers_unites", "depuis_unites", "somme_exacte", "UNMEASURABLE"]
