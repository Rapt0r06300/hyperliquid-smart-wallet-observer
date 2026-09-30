"""[EXEC pépite 214] INTENT ID ≠ VENUE ORDER ID : ne JAMAIS confondre l'INTENTION économique stable (une seule par
décision) et l'IDENTIFIANT VENUE, recréé à CHAQUE remplacement. Compter chaque venue-id comme une position distincte
gonfle l'exposition ; une intention peut porter plusieurs venue-ids successifs, mais reste UNE position. Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any


class RegistreIntentVenue:
    """Associe des venue-order-ids (multiples, changeants) à leur intent-id (unique, stable)."""

    def __init__(self) -> None:
        self._venue_vers_intent: dict[str, str] = {}
        self._intent_venues: dict[str, list[str]] = {}

    def lier(self, *, intent_id: str, venue_order_id: str) -> None:
        self._venue_vers_intent[str(venue_order_id)] = str(intent_id)
        self._intent_venues.setdefault(str(intent_id), [])
        if str(venue_order_id) not in self._intent_venues[str(intent_id)]:
            self._intent_venues[str(intent_id)].append(str(venue_order_id))

    def intent_de(self, venue_order_id: str) -> Any:
        return self._venue_vers_intent.get(str(venue_order_id))

    def n_positions_distinctes(self) -> int:
        """Nombre d'INTENTIONS distinctes (= positions), pas de venue-ids (qui peuvent être nombreux par intent)."""
        return len(self._intent_venues)

    def venues_de(self, intent_id: str) -> list[str]:
        return list(self._intent_venues.get(str(intent_id), []))


__all__ = ["RegistreIntentVenue"]
