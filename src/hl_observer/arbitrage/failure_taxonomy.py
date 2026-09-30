"""[ARB #35] FAILURE TAXONOMY : classer chaque échec d'exécution simulée en catégories distinctes — timeout,
reject, stale price, insufficient liquidity, invalid quantity, connector failure, unknown-state. Sans taxonomie,
tous les échecs sont traités pareil et on applique le mauvais remède. Un échec non reconnu reste UNKNOWN_STATE
(jamais requalifié en succès). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

TIMEOUT = "TIMEOUT"
REJECT = "REJECT"
STALE_PRICE = "STALE_PRICE"
INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
INVALID_QUANTITY = "INVALID_QUANTITY"
CONNECTOR_FAILURE = "CONNECTOR_FAILURE"
UNKNOWN_STATE = "UNKNOWN_STATE"

CATEGORIES = (TIMEOUT, REJECT, STALE_PRICE, INSUFFICIENT_LIQUIDITY, INVALID_QUANTITY,
              CONNECTOR_FAILURE, UNKNOWN_STATE)

_MOTIFS = {
    TIMEOUT: ("TIMEOUT", "TIMED_OUT", "DEADLINE", "NO_RESPONSE"),
    STALE_PRICE: ("STALE", "PRICE_MOVED", "QUOTE_EXPIRED", "OLD_QUOTE"),
    INSUFFICIENT_LIQUIDITY: ("INSUFFICIENT_LIQUIDITY", "NO_LIQUIDITY", "THIN_BOOK", "NOT_ENOUGH_DEPTH"),
    INVALID_QUANTITY: ("INVALID_QUANTITY", "MIN_SIZE", "LOT_SIZE", "TICK_SIZE", "TOO_SMALL", "MIN_NOTIONAL"),
    CONNECTOR_FAILURE: ("CONNECTOR", "DISCONNECT", "SOCKET", "5XX", "GATEWAY", "UNAVAILABLE"),
    REJECT: ("REJECT", "REJECTED", "REFUSED", "DENIED"),
}


def classifier(signal: Any) -> dict[str, Any]:
    """Mappe un code/message d'échec vers UNE catégorie. Ordre de priorité : les motifs spécifiques (stale,
    liquidité, quantité, connecteur, timeout) avant le REJECT générique. Non reconnu → UNKNOWN_STATE."""
    s = str(signal).upper()
    for cat in (TIMEOUT, STALE_PRICE, INSUFFICIENT_LIQUIDITY, INVALID_QUANTITY, CONNECTOR_FAILURE, REJECT):
        if any(m in s for m in _MOTIFS[cat]):
            return {"categorie": cat, "reconnue": True}
    return {"categorie": UNKNOWN_STATE, "reconnue": False}


__all__ = ["classifier", "CATEGORIES", "TIMEOUT", "REJECT", "STALE_PRICE", "INSUFFICIENT_LIQUIDITY",
           "INVALID_QUANTITY", "CONNECTOR_FAILURE", "UNKNOWN_STATE"]
