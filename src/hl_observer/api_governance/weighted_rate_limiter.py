"""[ALL lot2 #23] RATE LIMITER PONDÉRÉ PAR ENDPOINT : chaque endpoint a un POIDS (un placeOrder coûte plus qu'un
getTime) ; le budget se compte en POIDS consommé par fenêtre, pas en simple « N requêtes/seconde ». Compter les
requêtes à l'unité sous-estime la charge et provoque des bans. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class LimiteurPondere:
    """Budget de poids par fenêtre glissante. `consommer` refuse si le poids ajouté dépasse le budget."""

    def __init__(self, *, budget_poids: float = 1000.0, fenetre_ms: float = 60_000.0) -> None:
        self.budget = float(budget_poids)
        self.fenetre_ms = float(fenetre_ms)
        self._events: list[tuple[float, float]] = []   # (ts_ms, poids)

    def poids_utilise(self, *, now_ms: float) -> float:
        self._events = [(t, w) for (t, w) in self._events if now_ms - t <= self.fenetre_ms]
        return round(sum(w for _, w in self._events), 6)

    def consommer(self, *, poids: Any, now_ms: float) -> dict[str, Any]:
        """Consomme `poids` si le budget de la fenêtre le permet ; sinon refuse (rien consommé)."""
        if not isinstance(poids, (int, float)) or float(poids) < 0:
            return {"ok": False, "raison": "POIDS_INVALIDE"}
        utilise = self.poids_utilise(now_ms=now_ms)
        if utilise + float(poids) > self.budget + 1e-9:
            return {"ok": False, "raison": "BUDGET_POIDS_DEPASSE", "utilise": utilise, "budget": self.budget}
        self._events.append((float(now_ms), float(poids)))
        return {"ok": True, "utilise": round(utilise + float(poids), 6), "budget": self.budget}


__all__ = ["LimiteurPondere"]
