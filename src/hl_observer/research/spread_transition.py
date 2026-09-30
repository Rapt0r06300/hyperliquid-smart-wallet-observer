"""ALPHA P51 — TRANSITION de spread / liquidité : prédire élargissement/resserrement, effondrement/récupération
de profondeur, et DÉCIDER : TAKER NOW / MAKER / WAIT / NO_TRADE.

Logique simple et explicable (baseline) : si le spread se resserre et la profondeur se reconstitue → MAKER
(on capture le spread) ; s'il s'élargit vite → TAKER NOW (avant que ça coûte plus) ou NO_TRADE si déjà trop
large ; incertain → WAIT. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def decision(*, spread_bps: Any, spread_tendance: Any, depth_tendance: Any,
             spread_max_taker_bps: float = 8.0) -> dict[str, Any]:
    """Décide l'action d'exécution depuis l'état du spread et les tendances (spread/profondeur)."""
    if not isinstance(spread_bps, (int, float)):
        return {"action": "NO_TRADE", "raison": "UNMEASURABLE"}
    st = spread_tendance if isinstance(spread_tendance, (int, float)) else 0.0
    dt = depth_tendance if isinstance(depth_tendance, (int, float)) else 0.0
    if spread_bps > spread_max_taker_bps and st > 0:
        return {"action": "NO_TRADE", "raison": "spread large et s'elargit"}
    if st < 0 and dt >= 0:
        return {"action": "MAKER", "raison": "spread se resserre, profondeur ok -> capturer le spread"}
    if st > 0:
        return {"action": "TAKER_NOW", "raison": "spread s'elargit -> agir avant que ca coute plus"}
    return {"action": "WAIT", "raison": "pas de signal de transition clair"}


__all__ = ["decision", "UNMEASURABLE"]
