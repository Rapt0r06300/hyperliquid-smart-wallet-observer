"""[COPY-VAULT #56] POST-ROUNDING NOTIONAL CHECK : après avoir arrondi la taille copiée (au lot/tick), RE-vérifier
le notional minimum exécutable. L'arrondi vers le bas peut faire tomber une petite copie sous le minimum de la
venue → l'ordre serait non exécutable. On valide APRÈS arrondi, pas avant. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any
import math


def verifier(taille_arrondie: Any, prix: Any, *, min_notional: float) -> dict[str, Any]:
    """OK seulement si taille_arrondie × prix ≥ min_notional. Entrées invalides → refus (jamais supposé OK)."""
    if not all(isinstance(x, (int, float)) for x in (taille_arrondie, prix)):
        return {"ok": False, "notional": None, "raison": "ENTREE_INVALIDE"}
    notional = abs(float(taille_arrondie)) * float(prix)
    ok = notional >= float(min_notional)
    return {"ok": bool(ok), "notional": round(notional, 8), "min_notional": float(min_notional),
            "raison": ("OK" if ok else "SOUS_MIN_APRES_ARRONDI")}


def post_rounding_economic_receipt(taille_arrondie: Any, prix: Any, *, fee_bps: Any, min_notional: Any) -> dict[str, Any]:
    """Recompute notional and fee from the rounded size, never pre-rounding size."""

    values = (taille_arrondie, prix, fee_bps, min_notional)
    if any(isinstance(value, bool) for value in values):
        return {"status": "UNMEASURABLE", "reason": "INPUT_INVALID"}
    try:
        size, px, fee, minimum = (float(value) for value in values)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "reason": "INPUT_INVALID"}
    if not all(math.isfinite(value) for value in (size, px, fee, minimum)) or min(size, px, fee, minimum) < 0.0:
        return {"status": "UNMEASURABLE", "reason": "INPUT_INVALID"}
    notional = size * px
    fee_amount = notional * fee / 10_000.0
    return {"status": "PROVEN", "notional": round(notional, 10), "fee": round(fee_amount, 10), "net_after_fee": round(notional - fee_amount, 10), "executable": bool(notional >= minimum)}


__all__ = ["verifier", "post_rounding_economic_receipt"]
