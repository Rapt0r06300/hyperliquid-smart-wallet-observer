"""[ARB lot2 #6] FOK POUR L'ARBITRAGE SYMÉTRIQUE : quand un fill PARTIEL détruirait l'économie de l'épisode
(arbitrage symétrique où les deux jambes doivent tenir ensemble), on utilise FOK (Fill-Or-Kill) : soit tout est
rempli d'un coup, soit RIEN. Un demi-arb rempli est pire que pas d'arb (jambe nue). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def simuler_fok(qte_demandee: Any, qte_disponible_immediate: Any) -> dict[str, Any]:
    """Tout ou rien : si la disponibilité immédiate couvre la quantité → fill complet ; sinon RIEN (kill).
    Jamais de fill partiel. Entrées invalides → UNMEASURABLE."""
    if not all(isinstance(x, (int, float)) for x in (qte_demandee, qte_disponible_immediate)) \
            or float(qte_demandee) <= 0 or float(qte_disponible_immediate) < 0:
        return {"remplie": UNMEASURABLE, "raison": "ENTREE_INVALIDE"}
    if float(qte_disponible_immediate) + 1e-12 >= float(qte_demandee):
        return {"remplie": round(float(qte_demandee), 12), "execute": True, "raison": "FILL_COMPLET"}
    return {"remplie": 0.0, "execute": False, "raison": "KILL_LIQUIDITE_INSUFFISANTE"}


__all__ = ["simuler_fok", "UNMEASURABLE"]
