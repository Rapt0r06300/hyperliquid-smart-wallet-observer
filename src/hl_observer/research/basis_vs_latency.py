"""ALPHA P50 — BASIS persistant vs DISLOCATION de latence (transient). Cross-venue ne trade QUE le transient.

Un écart de prix inter-venues peut être : (a) un BASIS structurel persistant (perp/spot, funding) → NON
tradable en latence, `DISABLED_BY_SCOPE` ; (b) une dislocation TRANSIENTE de latence qui converge vite →
seule tradable. On classe par l'autocorrélation lag-1 et la demi-vie de retour à la moyenne de l'écart.

Mesuré : autocorr proche de 1 + demi-vie longue ⇒ basis persistant. Retour rapide ⇒ transient.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def autocorr1(serie: Sequence[float]) -> float | None:
    v = [float(x) for x in serie]
    n = len(v)
    if n < 20:
        return None
    m = sum(v) / n
    den = sum((x - m) ** 2 for x in v)
    if den <= 0:
        return None
    num = sum((v[i] - m) * (v[i - 1] - m) for i in range(1, n))
    return num / den


def demi_vie_pas(rho1: float | None) -> float | None:
    """Demi-vie (en pas) d'un AR(1) de coefficient rho1 : ln(0.5)/ln(rho1). None si rho1 hors (0,1)."""
    if rho1 is None or not (0.0 < rho1 < 1.0):
        return None
    return math.log(0.5) / math.log(rho1)


def classer_dislocation(serie_gap_bps: Sequence[float], *, dt_s: float = 1.0,
                        seuil_autocorr: float = 0.5, seuil_demi_vie_s: float = 30.0) -> dict[str, Any]:
    """Classe l'écart inter-venues : persistent_basis vs transient. Le cross-venue ne trade que transient."""
    rho = autocorr1(serie_gap_bps)
    hv_pas = demi_vie_pas(rho)
    hv_s = (hv_pas * dt_s) if hv_pas is not None else None
    if rho is None:
        return {"classe": UNMEASURABLE, "autocorr1": UNMEASURABLE, "demi_vie_s": UNMEASURABLE,
                "persistent_basis": UNMEASURABLE, "transient": UNMEASURABLE}
    persistent = bool(rho >= seuil_autocorr and (hv_s is None or hv_s >= seuil_demi_vie_s))
    return {"classe": ("PERSISTENT_BASIS" if persistent else "TRANSIENT_DISLOCATION"),
            "autocorr1": round(rho, 4), "demi_vie_s": (round(hv_s, 3) if hv_s is not None else UNMEASURABLE),
            "persistent_basis": persistent, "transient": (not persistent)}


def gate_cross_venue(classification: dict[str, Any], *, edge_bps: float | None, cost_bps: float | None) -> dict[str, Any]:
    """N'autorise le cross-venue que si TRANSIENT et edge exécutable > coût. Le basis est hors scope."""
    if classification.get("persistent_basis") is True:
        return {"trade": False, "raison": "PERSISTENT_BASIS_DISABLED_BY_SCOPE"}
    if not isinstance(edge_bps, (int, float)) or not isinstance(cost_bps, (int, float)):
        return {"trade": False, "raison": "UNMEASURABLE"}
    ok = edge_bps > cost_bps
    return {"trade": bool(ok), "raison": ("OK_TRANSIENT" if ok else "EDGE<=COUT")}


__all__ = ["autocorr1", "demi_vie_pas", "classer_dislocation", "gate_cross_venue", "UNMEASURABLE"]
