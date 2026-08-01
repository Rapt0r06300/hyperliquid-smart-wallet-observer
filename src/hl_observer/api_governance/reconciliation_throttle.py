"""[ALL lot2 #27] THROTTLE DES QUERIES DE RÉCONCILIATION : les queries de réconciliation sont throttlées
spécifiquement, pour éviter une TEMPÊTE REST juste après une panne WS (au retour, on voudrait tout re-vérifier d'un
coup et on épuiserait le quota / on se ferait bannir). Un intervalle minimum est imposé entre deux réconciliations.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class ThrottleReconciliation:
    """Impose un intervalle minimum entre deux queries de réconciliation par clé (ex. venue)."""

    def __init__(self, *, intervalle_min_ms: float = 1000.0) -> None:
        self.intervalle_min_ms = float(intervalle_min_ms)
        self._dernier_ms: dict[str, float] = {}

    def peut_query(self, cle: str, *, now_ms: Any) -> dict[str, Any]:
        """Autorise seulement si l'intervalle minimum est écoulé depuis la dernière query de cette clé."""
        if not isinstance(now_ms, (int, float)):
            return {"ok": False, "raison": "TEMPS_INVALIDE"}
        dernier = self._dernier_ms.get(str(cle))
        if dernier is not None and float(now_ms) - dernier < self.intervalle_min_ms:
            return {"ok": False, "attendre_ms": round(self.intervalle_min_ms - (float(now_ms) - dernier), 3),
                    "raison": "THROTTLE_RECONCILIATION"}
        return {"ok": True, "raison": "OK"}

    def marquer(self, cle: str, *, now_ms: float) -> None:
        self._dernier_ms[str(cle)] = float(now_ms)


__all__ = ["ThrottleReconciliation"]
