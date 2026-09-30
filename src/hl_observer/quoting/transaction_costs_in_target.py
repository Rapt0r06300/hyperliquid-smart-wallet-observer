"""[CROSS-VENUE lot2 #83] TRANSACTION COSTS DANS LE MAKER TARGET PRICE : incorporer les coûts de transaction
DIRECTEMENT dans le prix cible maker, pas seulement dans le rapport PnL final. Poster à un prix qui ignore les frais,
c'est afficher un edge qui n'existe pas une fois les coûts payés ; on décale le prix cible pour qu'il intègre déjà
le coût (Hummingbot : add_transaction_costs_to_orders). Prix invalide → UNMEASURABLE. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def prix_cible(prix_base: Any, sens: Any, *, cout_bps: float) -> dict[str, Any]:
    """Décale le prix cible pour couvrir le coût : à l'ACHAT on vise plus bas (payer moins pour absorber le coût),
    à la VENTE on vise plus haut. Le prix posté intègre donc déjà les frais. Prix invalide → UNMEASURABLE."""
    if not isinstance(prix_base, (int, float)) or float(prix_base) <= 0:
        return {"prix_cible": UNMEASURABLE, "raison": "PRIX_INVALIDE"}
    s = str(sens).upper()
    facteur = float(cout_bps) / 1e4
    if s in ("ACHAT", "BUY", "LONG"):
        cible = float(prix_base) * (1.0 - facteur)
    elif s in ("VENTE", "SELL", "SHORT"):
        cible = float(prix_base) * (1.0 + facteur)
    else:
        return {"prix_cible": UNMEASURABLE, "raison": "SENS_INCONNU"}
    return {"prix_cible": round(cible, 10), "cout_bps": float(cout_bps), "prix_base": float(prix_base)}


__all__ = ["prix_cible", "UNMEASURABLE"]
