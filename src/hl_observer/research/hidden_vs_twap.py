"""ALPHA P28 — HIDDEN FLOW × VISIBLE TWAP : interaction d'un TWAP visible et d'un flux caché même direction.

Quand un TWAP visible s'exécute EN MÊME TEMPS qu'un flux caché de même sens, l'impact permanent et le crowding
changent. On mesure : impact permanent (déplacement du mid conservé après), réponse de la profondeur, toxicité
(sélection adverse accrue). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def impact_permanent_bps(mid_avant: Any, mid_apres_relaxation: Any) -> Any:
    """Impact permanent = déplacement conservé du mid après relaxation. UNMEASURABLE si inconnu."""
    if not isinstance(mid_avant, (int, float)) or not isinstance(mid_apres_relaxation, (int, float)) or mid_avant <= 0:
        return UNMEASURABLE
    return round((mid_apres_relaxation / mid_avant - 1.0) * 1e4, 4)


def interaction(*, twap_sens: int, hidden_sens: Any = None, impact_bps: Any = None,
                depth_response: Any = None) -> dict[str, Any]:
    """Qualifie l'interaction : crowding (même sens) amplifie l'impact et la toxicité."""
    meme_sens = isinstance(hidden_sens, (int, float)) and (hidden_sens * twap_sens > 0)
    tox = UNMEASURABLE
    if isinstance(impact_bps, (int, float)):
        # toxicité proxy : impact permanent élevé + profondeur qui ne se reconstitue pas
        dr = depth_response if isinstance(depth_response, (int, float)) else 0.5
        tox = round(max(0.0, min(1.0, abs(impact_bps) / 20.0 * (1.0 - dr))), 4)
    return {"crowding_meme_sens": meme_sens, "impact_permanent_bps": impact_bps,
            "toxicite": tox,
            "note": "TWAP visible + flux cache meme sens = crowding -> impact/toxicite accrus"}


__all__ = ["impact_permanent_bps", "interaction", "UNMEASURABLE"]
