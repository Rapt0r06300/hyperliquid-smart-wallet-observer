"""R9 — Promotion par calibration + quarantaine (CloddsBot / evan-kolberg).

Decide si un signal/strategie peut trader en paper selon la qualite de calibration
(ecart de Brier / calibration gap) et un echantillon suffisant. Pur.
PROMOTE = tradeable ; SHADOW = observe sans trader ; QUARANTINE = ecarte.
"""

from __future__ import annotations

DEFAULT_MAX_CALIB_GAP = 0.10   # ecart calibration tolere
DEFAULT_MIN_SAMPLE = 30


def promotion_decision(
    calibration_gap: float | None,
    sample: int,
    *,
    quarantined: bool = False,
    max_gap: float = DEFAULT_MAX_CALIB_GAP,
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> str:
    if quarantined:
        return "QUARANTINE"
    if calibration_gap is None or sample < min_sample:
        return "SHADOW"                      # pas assez de preuve -> on observe
    if abs(calibration_gap) <= max_gap:
        return "PROMOTE"
    return "SHADOW"


def is_tradeable(calibration_gap, sample, **kw) -> bool:
    return promotion_decision(calibration_gap, sample, **kw) == "PROMOTE"


__all__ = ["promotion_decision", "is_tradeable", "DEFAULT_MAX_CALIB_GAP", "DEFAULT_MIN_SAMPLE"]
