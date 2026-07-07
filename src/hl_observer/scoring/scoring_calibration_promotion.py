"""V14 #184 — Blend maker-band + DEB-ensemble + EMOS calibration into the ranking score.

A transparent, monotone combination used for RANKING only (never creates a trade):
 - base_score 0..1 from the realtime scorer,
 - maker_band_adj in [-1,1] (favourable LP band positioning nudges up),
 - deb_weight in [0,1] (down-weight models/strategies that have been wrong lately),
 - emos_factor in (0,~1.2] (probabilistic calibration multiplier).
Pure; clamped to [0,1].
"""

from __future__ import annotations


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def combine_calibrated_score(
    *,
    base_score: float,
    maker_band_adj: float = 0.0,
    deb_weight: float = 1.0,
    emos_factor: float = 1.0,
) -> float:
    base = _clamp(float(base_score))
    band = base * (1.0 + 0.10 * max(-1.0, min(1.0, float(maker_band_adj))))  # +/-10% nudge
    weighted = band * _clamp(float(deb_weight))
    calibrated = weighted * max(0.0, float(emos_factor))
    return round(_clamp(calibrated), 6)


__all__ = ["combine_calibrated_score"]
