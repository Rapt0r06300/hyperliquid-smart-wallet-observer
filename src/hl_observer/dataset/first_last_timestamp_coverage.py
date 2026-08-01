"""[DATA pépite 260] FIRST/LAST TIMESTAMP COVERAGE : pour chaque dataset on stocke la PREMIÈRE et la DERNIÈRE
observation effective, et la couverture réelle par rapport à la fenêtre attendue. Sans ça, un dataset qui
commence 6h trop tard est utilisé comme s'il couvrait toute la période — et le backtest ment. La couverture est
un ratio observé/attendu, plafonné à 1.0. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any


class CouvertureDataset:
    """Accumule min/max des timestamps observés. resume(debut, fin) rend premier/dernier/span et le ratio de
    couverture réel sur la fenêtre attendue. Aucune observation → couverture 0.0 (honnête, pas 1.0 optimiste)."""

    def __init__(self) -> None:
        self._premier: Any = None
        self._dernier: Any = None
        self._n = 0

    def observer(self, ts: Any) -> None:
        if not isinstance(ts, (int, float)) or isinstance(ts, bool) or not math.isfinite(ts):
            return
        self._n += 1
        if self._premier is None or ts < self._premier:
            self._premier = ts
        if self._dernier is None or ts > self._dernier:
            self._dernier = ts

    def resume(self, debut_attendu: float, fin_attendu: float) -> dict[str, Any]:
        if self._n == 0 or fin_attendu <= debut_attendu:
            return {"premier": self._premier, "dernier": self._dernier, "n": self._n,
                    "span_observe": 0.0, "couverture": 0.0}
        span_obs = float(self._dernier) - float(self._premier)
        span_att = float(fin_attendu) - float(debut_attendu)
        couverture = max(0.0, min(1.0, span_obs / span_att))
        return {"premier": self._premier, "dernier": self._dernier, "n": self._n,
                "span_observe": round(span_obs, 6), "couverture": round(couverture, 6)}


__all__ = ["CouvertureDataset"]
