"""J1 — FEATURE STORE POINT-IN-TIME : le socle anti-lookahead.

Chaque feature est stockée avec son timestamp de DISPONIBILITÉ RÉELLE. Au backtest, `as_of(t)` ne
renvoie JAMAIS une valeur estampillée APRÈS t — impossible de lire le futur par construction. C'est
la garde structurelle contre le lookahead (la maladie qui fabrique de faux edges). PAPER only.
"""
from __future__ import annotations

import bisect


class FeatureStore:
    def __init__(self) -> None:
        self._data: dict[str, list[tuple[int, object]]] = {}   # nom -> [(ts_ms, valeur)] trié par ts

    def ecrire(self, nom: str, ts_ms: int, valeur: object) -> None:
        serie = self._data.setdefault(str(nom), [])
        ts = int(ts_ms)
        i = bisect.bisect_left([t for t, _ in serie], ts)
        if i < len(serie) and serie[i][0] == ts:
            serie[i] = (ts, valeur)                            # écrase la même estampille
        else:
            serie.insert(i, (ts, valeur))

    def as_of(self, nom: str, ts_query_ms: int):
        """La DERNIÈRE valeur disponible AU PLUS TARD à ts_query. None si aucune. Jamais le futur."""
        serie = self._data.get(str(nom))
        if not serie:
            return None
        i = bisect.bisect_right([t for t, _ in serie], int(ts_query_ms)) - 1
        return serie[i][1] if i >= 0 else None

    def historique(self, nom: str) -> list[tuple[int, object]]:
        return list(self._data.get(str(nom), []))


__all__ = ["FeatureStore"]
