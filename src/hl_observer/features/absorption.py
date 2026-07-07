"""V15 #189 — Absorption score: panic flush ABSORBED then stabilised (0..1).

A high score means a sharp adverse move met heavy opposing volume and price then held
(sellers/buyers absorbed) — a classic reversal setup. Pure.
"""

from __future__ import annotations

from dataclasses import dataclass


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass(frozen=True, slots=True)
class AbsorptionResult:
    score: float            # 0..1
    panicked: bool
    stabilised: bool


def absorption_score(
    *,
    adverse_move_bps: float,
    opposing_volume_ratio: float,    # opposing aggressor vol / total, 0..1
    recovery_bps: float,             # how much price came back after the flush
    panic_threshold_bps: float = 40.0,
) -> AbsorptionResult:
    panicked = abs(float(adverse_move_bps)) >= panic_threshold_bps
    stabilised = float(recovery_bps) >= abs(float(adverse_move_bps)) * 0.3
    vol_factor = _clamp(float(opposing_volume_ratio))
    move_factor = _clamp(abs(float(adverse_move_bps)) / max(1.0, panic_threshold_bps * 2.0))
    recover_factor = _clamp(float(recovery_bps) / max(1.0, abs(float(adverse_move_bps)) or 1.0))
    raw = 0.4 * vol_factor + 0.3 * move_factor + 0.3 * recover_factor
    score = raw if (panicked and stabilised) else raw * 0.4
    return AbsorptionResult(round(_clamp(score), 6), panicked, stabilised)


__all__ = ["AbsorptionResult", "absorption_score"]
