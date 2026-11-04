"""ALPHA P24 — CALIBRATION du modèle de QUEUE maker : baseline RiskAverse vs challenger probabiliste.

Un ordre maker n'est PAS rempli dès que le prix touche : il faut que la queue DEVANT nous soit consommée
avant que le prix reparte. Baseline `RiskAverseQueue` : rempli seulement si le volume agressif traversant
dépasse la queue devant (prudent). Challenger probabiliste : probabilité de fill = f(volume traversant /
queue devant). Sans priorité L4 réelle, on calibre sur trade-through / cancellations / depletion.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any
import math

UNMEASURABLE = "UNMEASURABLE"


def fill_risk_averse(queue_ahead: Any, volume_traversant: Any) -> dict[str, Any]:
    """Baseline prudente : fill seulement si le volume agressif traversant > queue devant nous."""
    if not isinstance(queue_ahead, (int, float)) or not isinstance(volume_traversant, (int, float)):
        return {"fill": UNMEASURABLE}
    return {"fill": bool(volume_traversant > queue_ahead), "modele": "RiskAverseQueue"}


def fill_probabiliste(queue_ahead: Any, volume_traversant: Any, *, cancels_devant: float = 0.0) -> dict[str, Any]:
    """Challenger : P(fill) = volume_traversant / (queue_ahead − cancels + volume_traversant). ∈ [0,1]."""
    if not isinstance(queue_ahead, (int, float)) or not isinstance(volume_traversant, (int, float)):
        return {"p_fill": UNMEASURABLE}
    q = max(0.0, float(queue_ahead) - float(cancels_devant))
    denom = q + float(volume_traversant)
    p = (float(volume_traversant) / denom) if denom > 0 else 0.0
    return {"p_fill": round(max(0.0, min(1.0, p)), 4), "modele": "ProbabilisticQueue"}


def comparer(queue_ahead: Any, volume_traversant: Any, *, cancels_devant: float = 0.0) -> dict[str, Any]:
    """Compare baseline (booléen) et challenger (probabilité) sur le même état de queue."""
    return {"risk_averse": fill_risk_averse(queue_ahead, volume_traversant),
            "probabiliste": fill_probabiliste(queue_ahead, volume_traversant, cancels_devant=cancels_devant),
            "note": "calibrer contre trade-through/cancellations reels ; priorite exacte requiert L4"}


def queue_model_limits_receipt(*, queue_ahead: object, volume_traversant: object, cancels_devant: object) -> dict[str, Any]:
    """Compare queue models only within observed non-negative limits."""

    try:
        queue, volume, cancels = float(queue_ahead), float(volume_traversant), float(cancels_devant)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "reason": "QUEUE_INPUT_INVALID"}
    if not all(math.isfinite(value) for value in (queue, volume, cancels)) or min(queue, volume, cancels) < 0.0:
        return {"status": "UNMEASURABLE", "reason": "QUEUE_INPUT_INVALID"}
    result = comparer(queue, volume, cancels_devant=cancels)
    return {"status": "PROVEN", "risk_averse": result["risk_averse"], "probabiliste": result["probabiliste"], "paper_only": True}


__all__ = ["fill_risk_averse", "fill_probabiliste", "comparer", "UNMEASURABLE"]
