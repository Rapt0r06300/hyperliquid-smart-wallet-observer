"""Calibrated freshness decay for the copy edge (S6 — V9, Harrier).

Problem this fixes
------------------
The live scorer multiplies the leader's expected edge by a *linear* freshness
factor ``1 - age/max_age``. That curve is brutal: with ``max_age = 30 s`` a signal
only 11 s old already keeps just 63 % of its edge, and at 25 s only 17 %. On real
data this single multiplier is the deepest reason fresh-but-not-instant signals
fall below the net-edge bar and never open.

A better, honest model
----------------------
Real copy edge does not vanish linearly. It is roughly *flat for the first few
seconds* (you are still early), then decays with a *half-life*, and only becomes
worthless once the move is clearly gone. This module implements exactly that:

    age <= grace_ms          -> 1.0                  (still early, full edge)
    grace_ms < age < hard_max -> exp(-(age-grace)/tau) with a floor
    age >= hard_max_ms        -> 0.0                  (stale: treat as no edge)

where ``tau`` is derived from a half-life (``tau = half_life / ln 2``).

It is a *drop-in* for ``realtime_magic_score.freshness_factor`` — same call shape
``f(age_ms, max_age_ms)`` via :func:`freshness_factor_calibrated` — so it can be
wired without touching the scoring formula's structure. Nothing here places an
order; it only scales an edge estimate. SAFETY: pure, deterministic, paper-only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_LN2 = math.log(2.0)


@dataclass(frozen=True, slots=True)
class FreshnessDecayConfig:
    grace_ms: int = 4_000
    """Below this age the signal keeps its full edge (still early)."""
    half_life_ms: int = 12_000
    """After the grace period, edge halves every ``half_life_ms``."""
    floor: float = 0.0
    """Minimum multiplier while the signal is not yet hard-stale."""
    hard_max_ms: int = 45_000
    """At/after this age the signal is stale -> multiplier 0.0 (no edge)."""

    def __post_init__(self) -> None:
        if self.grace_ms < 0:
            raise ValueError("grace_ms must be >= 0")
        if self.half_life_ms <= 0:
            raise ValueError("half_life_ms must be > 0")
        if not (0.0 <= self.floor <= 1.0):
            raise ValueError("floor must be in [0, 1]")
        if self.hard_max_ms <= self.grace_ms:
            raise ValueError("hard_max_ms must be > grace_ms")


def freshness_multiplier(age_ms: float, config: FreshnessDecayConfig | None = None) -> float:
    """Return a freshness multiplier in [0, 1] for a signal of ``age_ms``."""
    cfg = config or FreshnessDecayConfig()
    age = max(0.0, float(age_ms))
    if age <= cfg.grace_ms:
        return 1.0
    if age >= cfg.hard_max_ms:
        return 0.0
    tau = cfg.half_life_ms / _LN2
    raw = math.exp(-(age - cfg.grace_ms) / tau)
    return max(cfg.floor, min(1.0, raw))


def decayed_edge(raw_edge_bps: float, age_ms: float, config: FreshnessDecayConfig | None = None) -> float:
    """Scale a raw edge (bps) by the calibrated freshness multiplier."""
    return raw_edge_bps * freshness_multiplier(age_ms, config)


def linear_freshness(age_ms: float, max_age_ms: float) -> float:
    """The *current* live curve, kept for comparison/parity (``1 - age/max``)."""
    if max_age_ms <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - max(0.0, float(age_ms)) / max_age_ms))


def freshness_factor_calibrated(signal_age_ms: int, max_signal_age_ms: int) -> float:
    """Drop-in replacement for ``realtime_magic_score.freshness_factor``.

    Maps the scorer's single ``max_signal_age_ms`` knob onto the calibrated
    curve: grace = 15 % of the window, half-life = 40 % of the window, and the
    window itself is the hard-stale cutoff. Preserves far more edge for genuinely
    fresh signals while still reaching 0 at the configured max age.
    """
    if max_signal_age_ms <= 0:
        return 0.0
    cfg = FreshnessDecayConfig(
        grace_ms=max(1, int(max_signal_age_ms * 0.15)),
        half_life_ms=max(1, int(max_signal_age_ms * 0.40)),
        floor=0.0,
        hard_max_ms=max(2, int(max_signal_age_ms)),
    )
    return freshness_multiplier(signal_age_ms, cfg)


__all__ = [
    "FreshnessDecayConfig",
    "freshness_multiplier",
    "decayed_edge",
    "linear_freshness",
    "freshness_factor_calibrated",
]
