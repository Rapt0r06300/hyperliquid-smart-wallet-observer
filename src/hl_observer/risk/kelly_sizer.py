"""Canonical capped Kelly sizing for local paper simulation.

Invalid, absent or non-finite inputs are rejected before any sizing calculation.
The function can only reduce or reject a paper intent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math


@dataclass(frozen=True, slots=True)
class KellySizerConfig:
    fraction: float = 0.25
    min_win_probability: float = 0.52
    max_equity_fraction: float = 0.05
    min_notional_usdt: float = 5.0
    max_notional_usdt: float = 50.0
    max_total_exposure_usdt: float = 200.0


@dataclass(frozen=True, slots=True)
class KellySizingDecision:
    accepted: bool
    notional_usdt: float
    full_kelly_fraction: float
    used_fraction: float
    win_probability: float
    win_loss_ratio: float
    reason_codes: tuple[str, ...] = field(default_factory=tuple)


def _finite(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _reject(*reasons: str, p: float = 0.0, b: float = 0.0) -> KellySizingDecision:
    return KellySizingDecision(False, 0.0, 0.0, 0.0, round(p, 8), round(b, 8), tuple(dict.fromkeys(reasons)))


def kelly_size_paper(
    *,
    win_probability: float,
    win_loss_ratio: float,
    equity_usdt: float,
    current_exposure_usdt: float = 0.0,
    config: KellySizerConfig | None = None,
) -> KellySizingDecision:
    cfg = config or KellySizerConfig()
    p = _finite(win_probability)
    b = _finite(win_loss_ratio)
    equity = _finite(equity_usdt)
    exposure = _finite(current_exposure_usdt)
    config_values = (
        cfg.fraction,
        cfg.min_win_probability,
        cfg.max_equity_fraction,
        cfg.min_notional_usdt,
        cfg.max_notional_usdt,
        cfg.max_total_exposure_usdt,
    )
    if any(_finite(value) is None for value in config_values):
        return _reject("KELLY_CONFIG_INVALID")
    if p is None or b is None or equity is None or exposure is None:
        return _reject("KELLY_INPUT_INVALID")
    if not 0.0 <= p <= 1.0:
        return _reject("KELLY_WIN_PROBABILITY_INVALID", p=p, b=max(b, 0.0))
    if (
        not 0.0 <= float(cfg.fraction) <= 1.0
        or not 0.0 <= float(cfg.min_win_probability) <= 1.0
        or float(cfg.max_equity_fraction) < 0.0
        or float(cfg.min_notional_usdt) < 0.0
        or float(cfg.max_notional_usdt) < float(cfg.min_notional_usdt)
        or float(cfg.max_total_exposure_usdt) < 0.0
    ):
        return _reject("KELLY_CONFIG_INVALID", p=p, b=max(b, 0.0))
    if b <= 0.0:
        return _reject("KELLY_WIN_LOSS_RATIO_INVALID", p=p, b=b)
    if equity <= 0.0 or exposure < 0.0:
        return _reject("KELLY_EQUITY_INVALID" if equity <= 0.0 else "KELLY_EXPOSURE_INVALID", p=p, b=b)
    if p < float(cfg.min_win_probability):
        return _reject("KELLY_WIN_PROBABILITY_TOO_LOW", p=p, b=b)

    full = (p * b - (1.0 - p)) / b
    if not math.isfinite(full) or full <= 0.0:
        return _reject("KELLY_NEGATIVE_EDGE", p=p, b=b)
    used_fraction = min(full * float(cfg.fraction), float(cfg.max_equity_fraction))
    raw_notional = equity * used_fraction
    remaining = max(0.0, float(cfg.max_total_exposure_usdt) - exposure)
    notional = min(raw_notional, float(cfg.max_notional_usdt), remaining)
    if not math.isfinite(notional) or notional < float(cfg.min_notional_usdt):
        return KellySizingDecision(False, 0.0, round(full, 8), round(used_fraction, 8), round(p, 8), round(b, 8), ("KELLY_NOTIONAL_BELOW_MINIMUM",))
    return KellySizingDecision(True, round(notional, 8), round(full, 8), round(used_fraction, 8), round(p, 8), round(b, 8))


__all__ = ["KellySizerConfig", "KellySizingDecision", "kelly_size_paper"]
