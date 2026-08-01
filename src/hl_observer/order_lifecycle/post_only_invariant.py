"""[CROSS-VENUE lot2 #8] POST-ONLY INVARIANT : un ordre prévu MAKER (post-only) qui croiserait le spread doit être
REJETÉ ou REPRICÉ — jamais exécuté en taker puis compté maker après coup. Compter maker un ordre qui a en réalité
payé le spread fausse le PnL (on croit toucher un rebate alors qu'on a payé le taker fee). Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

ACCEPTE = "ACCEPTE"
REJETE = "REJETE"


def verifier(prix_ordre: Any, meilleur_oppose: Any, sens: Any) -> dict[str, Any]:
    """Un BUY post-only doit rester < meilleur ask ; un SELL post-only > meilleur bid. S'il croise → REJETE
    (à repricer), jamais accepté comme maker. Prix invalide/sens inconnu → REJETE (prudence)."""
    if not all(isinstance(x, (int, float)) for x in (prix_ordre, meilleur_oppose)):
        return {"decision": REJETE, "raison": "PRIX_INVALIDE"}
    s = str(sens).upper()
    if s in ("ACHAT", "BUY", "LONG"):
        croise = float(prix_ordre) >= float(meilleur_oppose)      # achat au niveau/au-dessus de l'ask = taker
    elif s in ("VENTE", "SELL", "SHORT"):
        croise = float(prix_ordre) <= float(meilleur_oppose)      # vente au niveau/en-dessous du bid = taker
    else:
        return {"decision": REJETE, "raison": "SENS_INCONNU"}
    if croise:
        return {"decision": REJETE, "maker": False, "raison": "CROISERAIT_LE_SPREAD_REPRICER"}
    return {"decision": ACCEPTE, "maker": True, "raison": "RESTE_MAKER"}


__all__ = ["verifier", "ACCEPTE", "REJETE"]
