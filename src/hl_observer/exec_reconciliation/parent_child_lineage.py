"""[EXEC pépite 212] PARENT/CHILD LINEAGE : un retry, un amend ou un remplacement restent RATTACHÉS au même
economic_intent_id. Une intention économique peut générer plusieurs ordres venue successifs (remplacements) ; sans
lignage, on comptabilise plusieurs positions distinctes pour ce qui est UNE intention. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class LignageIntent:
    """Rattache chaque ordre venue (retry/amend/replacement) à son economic_intent_id d'origine."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def enregistrer(self, *, economic_intent_id: str, venue_order_id: str) -> None:
        self._parent[str(venue_order_id)] = str(economic_intent_id)

    def intent_de(self, venue_order_id: str) -> Any:
        return self._parent.get(str(venue_order_id))

    def ordres_de(self, economic_intent_id: str) -> list[str]:
        return sorted(o for o, p in self._parent.items() if p == str(economic_intent_id))

    def meme_intent(self, order_a: str, order_b: str) -> dict[str, Any]:
        """Deux ordres appartiennent-ils à la même intention économique ? Un rattachement inconnu → False."""
        ia, ib = self.intent_de(order_a), self.intent_de(order_b)
        ok = ia is not None and ia == ib
        return {"meme_intent": bool(ok), "intent": (ia if ok else None)}


__all__ = ["LignageIntent"]
