"""[DATA pépite 268] CROSSED-BOOK QUARANTINE : un snapshot où best_bid > best_ask, hors état explicitement
valide (ex. venue signalant un croisement transitoire documenté), est INEXPLOITABLE. On ne calcule ni mid ni
spread dessus, on ne prend aucune décision : le snapshot est mis en quarantaine plutôt que « réparé »
silencieusement. Entrées non numériques → quarantaine (fail-closed). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

EXPLOITABLE = "EXPLOITABLE"
QUARANTAINE = "QUARANTAINE"


def _fini(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def verifier(best_bid: Any, best_ask: Any, *, etat_valide_explicite: bool = False) -> dict[str, Any]:
    """best_bid > best_ask → QUARANTAINE, sauf si la venue déclare explicitement un état croisé valide.
    Prix non finis / non numériques → QUARANTAINE. Un carnet plat (bid == ask) reste exploitable."""
    if not (_fini(best_bid) and _fini(best_ask)):
        return {"etat": QUARANTAINE, "raison": "PRIX_NON_NUMERIQUE"}
    if best_bid > best_ask:
        if etat_valide_explicite:
            return {"etat": EXPLOITABLE, "croise": True, "raison": "CROISEMENT_DECLARE_VALIDE"}
        return {"etat": QUARANTAINE, "croise": True, "raison": "BID_SUPERIEUR_ASK"}
    return {"etat": EXPLOITABLE, "croise": False, "spread": round(float(best_ask) - float(best_bid), 12)}


__all__ = ["verifier", "EXPLOITABLE", "QUARANTAINE"]
