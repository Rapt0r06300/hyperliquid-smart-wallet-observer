"""[ARB #36] FAILURE-SPECIFIC RETRY : le remède dépend de la catégorie d'échec (#35). Un timeout impose une
RÉCONCILIATION (l'ordre est peut-être passé) ; une invalid quantity impose un RECALCUL ; une stale quote impose
l'ABANDON (le prix n'existe plus). Appliquer le même retry à tous les échecs est faux. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

from hl_observer.arbitrage.failure_taxonomy import (
    CONNECTOR_FAILURE, INSUFFICIENT_LIQUIDITY, INVALID_QUANTITY, REJECT, STALE_PRICE, TIMEOUT, UNKNOWN_STATE,
    classifier,
)

RECONCILIER = "RECONCILIER"        # état ambigu : lire l'ordre avant tout
RECALCULER = "RECALCULER"          # taille invalide : re-préflight tick/lot/min-notional
ABANDONNER = "ABANDONNER"          # prix périmé / plus d'opportunité
REESSAYER = "REESSAYER"            # échec transitoire : retry (éventuellement backoff)
ATTENDRE_ET_REESSAYER = "ATTENDRE_ET_REESSAYER"

_POLITIQUE = {
    TIMEOUT: RECONCILIER,                       # peut être passé -> réconcilier, jamais renvoyer aveugle
    UNKNOWN_STATE: RECONCILIER,
    INVALID_QUANTITY: RECALCULER,
    STALE_PRICE: ABANDONNER,
    INSUFFICIENT_LIQUIDITY: ABANDONNER,
    CONNECTOR_FAILURE: ATTENDRE_ET_REESSAYER,
    REJECT: REESSAYER,
}


def politique_retry(signal: Any) -> dict[str, Any]:
    """Classe l'échec (#35) puis choisit le remède adapté. Catégorie inconnue → RECONCILIER (prudence)."""
    cat = classifier(signal)["categorie"]
    action = _POLITIQUE.get(cat, RECONCILIER)
    return {"categorie": cat, "action": action}


__all__ = ["politique_retry", "RECONCILIER", "RECALCULER", "ABANDONNER", "REESSAYER", "ATTENDRE_ET_REESSAYER"]
