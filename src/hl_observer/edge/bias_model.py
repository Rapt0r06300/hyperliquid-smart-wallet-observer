"""Multi-timeframe directional bias -> edge adjustment (S6 — V9, mlmodelpoly A3).

Turns the multi-TF direction read into a small *signed* edge adjustment (bps) for
a copy entry: a fill aligned with the prevailing 5m/15m trend gets a modest edge
bonus; a fill fighting the trend gets a penalty; a flat/conflicting read is
neutral. The adjustment is bounded (``max_bias_bps``) so it can refine — never
dominate — the net-edge decision.

Pure and deterministic; built on ``features.direction``. SAFETY: read-only,
advisory only — it never turns a NO_TRADE into a forced trade on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

from hl_observer.features.direction import (
    DirectionConfig,
    MultiTFDirection,
    aligns_with,
    multi_tf_direction,
)


@dataclass(frozen=True, slots=True)
class BiasConfig:
    max_bias_bps: float = 8.0
    strength_scale: float = 0.15      # bps of bias per bp of TF strength, before clamp
    agree_bonus_bps: float = 2.0      # extra when both TFs agree


@dataclass(frozen=True, slots=True)
class BiasResult:
    bias_bps: float           # signed: + improves edge, - penalises
    aligned: bool
    combined: str
    agree: bool


def directional_bias_bps(
    direction_side: str,
    mtf: MultiTFDirection,
    config: BiasConfig | None = None,
) -> BiasResult:
    """Signed edge adjustment (bps) for an entry given the multi-TF read."""
    cfg = config or BiasConfig()
    aligned = aligns_with(direction_side, mtf.combined)
    magnitude = min(cfg.max_bias_bps, abs(mtf.strength_bps) * cfg.strength_scale)
    if mtf.combined == "FLAT":
        bias = 0.0
    elif aligned:
        bias = magnitude + (cfg.agree_bonus_bps if mtf.agree else 0.0)
    else:
        bias = -(magnitude + (cfg.agree_bonus_bps if mtf.agree else 0.0))
    bias = max(-cfg.max_bias_bps, min(cfg.max_bias_bps, bias))
    return BiasResult(
        bias_bps=round(bias, 6),
        aligned=aligned,
        combined=mtf.combined,
        agree=mtf.agree,
    )


def bias_from_closes(
    *,
    direction_side: str,
    closes_fast_tf: list[float],
    closes_slow_tf: list[float],
    direction_config: DirectionConfig | None = None,
    bias_config: BiasConfig | None = None,
) -> BiasResult:
    """Convenience: compute the multi-TF read from closes, then the bias."""
    mtf = multi_tf_direction(closes_fast_tf, closes_slow_tf, direction_config)
    return directional_bias_bps(direction_side, mtf, bias_config)


__all__ = [
    "BiasConfig",
    "BiasResult",
    "directional_bias_bps",
    "bias_from_closes",
]
