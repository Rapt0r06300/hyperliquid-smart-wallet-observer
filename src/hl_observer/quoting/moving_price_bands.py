"""[CROSS-VENUE lot2 #78] MOVING PRICE BANDS : les quotes sont INTERDITES lorsqu'elles sortent d'une enveloppe
recalculée périodiquement autour du prix de marché. Une quote qui dérive hors de la bande (référence figée, prix
qui a bougé) ne reflète plus le marché et serait toxique. Prix invalide → hors bande (fail-closed). Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any


def dans_bande(prix_quote: Any, prix_reference: Any, *, demi_bande_bps: float = 50.0) -> dict[str, Any]:
    """Autorise la quote seulement si son écart au prix de référence ≤ demi_bande. Prix invalide → interdite."""
    if not all(isinstance(x, (int, float)) for x in (prix_quote, prix_reference)) or float(prix_reference) <= 0:
        return {"autorisee": False, "raison": "PRIX_INVALIDE"}
    ecart_bps = abs(float(prix_quote) - float(prix_reference)) / float(prix_reference) * 1e4
    ok = ecart_bps <= float(demi_bande_bps)
    return {"autorisee": bool(ok), "ecart_bps": round(ecart_bps, 4), "demi_bande_bps": float(demi_bande_bps),
            "raison": ("OK" if ok else "HORS_BANDE")}


__all__ = ["dans_bande"]
