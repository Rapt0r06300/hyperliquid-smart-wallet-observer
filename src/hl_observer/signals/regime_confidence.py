"""V15 #193 — Regime-adjusted confidence (RANGE -> reduced; misalignment -> reduced)."""

from __future__ import annotations


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def regime_adjusted_confidence(
    base_confidence: float,
    *,
    regime: str,
    aligned: bool = True,
    range_factor: float = 0.8,
    misalign_factor: float = 0.7,
    panic_factor: float = 0.0,
) -> float:
    """Trend keeps confidence; range trims it; panic kills it; misalignment trims it."""
    conf = _clamp(float(base_confidence))
    r = str(regime or "").lower()
    if r in {"panic", "extreme"}:
        conf *= panic_factor
    elif r == "range":
        conf *= range_factor
    if not aligned:
        conf *= misalign_factor
    return round(_clamp(conf), 6)


__all__ = ["regime_adjusted_confidence"]
