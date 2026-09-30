"""J6 — MONITEUR DE DRIFT des features : alerter quand la distribution CHANGE.

Une feature dont la distribution dérive = le marché a changé sous le modèle -> revalider/désactiver
(anti-décroissance silencieuse). On compare une fenêtre RÉCENTE à une RÉFÉRENCE : décalage de
moyenne (en sigmas de la référence) et ratio d'écart-type. PAPER only.
"""
from __future__ import annotations

from typing import Sequence

SEUIL_DECALAGE_SIGMA = 1.0       # moyenne décalée de > 1 sigma de la reference = drift
SEUIL_RATIO_STD = 2.0            # vol qui double (ou diminue de moitié) = drift


def _stats(xs: Sequence[float]):
    v = [float(x) for x in xs or [] if isinstance(x, (int, float))]
    if len(v) < 2:
        return None
    m = sum(v) / len(v)
    sd = (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5
    return m, sd


def drift(reference: Sequence[float], recent: Sequence[float], *,
          seuil_sigma: float = SEUIL_DECALAGE_SIGMA, seuil_ratio: float = SEUIL_RATIO_STD) -> dict | None:
    """Renvoie {decalage_sigma, ratio_std, drift_detecte} ou None si non mesurable."""
    sr, sc = _stats(reference), _stats(recent)
    if sr is None or sc is None:
        return None
    (mr, sdr), (mc, sdc) = sr, sc
    decalage = abs(mc - mr) / sdr if sdr > 1e-12 else 0.0
    ratio = (sdc / sdr) if sdr > 1e-12 else 0.0
    detecte = decalage > float(seuil_sigma) or ratio >= float(seuil_ratio) or (ratio > 0 and ratio <= 1.0 / float(seuil_ratio))
    return {"decalage_sigma": round(decalage, 4), "ratio_std": round(ratio, 4), "drift_detecte": detecte}


__all__ = ["SEUIL_DECALAGE_SIGMA", "SEUIL_RATIO_STD", "drift"]
