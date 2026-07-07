"""Canonical capped Kelly sizing for local paper simulation.

The function is intentionally conservative: it can reduce or reject size, never
force an entry. It is suitable for copy-trading, arbitrage simulations and
strategy tournaments that estimate probability and payoff ratio.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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


def kelly_size_paper(
    *,
    win_probability: float,
    win_loss_ratio: float,
    equity_usdt: float,
    current_exposure_usdt: float = 0.0,
    config: KellySizerConfig | None = None,
) -> KellySizingDecision:
    cfg = config or KellySizerConfig()
    p = max(0.0, min(1.0, float(win_probability or 0.0)))
    b = max(0.0, float(win_loss_ratio or 0.0))
    equity = max(0.0, float(equity_usdt or 0.0))
    exposure = max(0.0, float(current_exposure_usdt or 0.0))
    reasons: list[str] = []
    if p < cfg.min_win_probability:
        reasons.append("KELLY_WIN_PROBABILITY_TOO_LOW")
    if b <= 0:
        reasons.append("KELLY_WIN_LOSS_RATIO_INVALID")
    if equity <= 0:
        reasons.append("KELLY_EQUITY_INVALID")
    if reasons:
        return KellySizingDecision(False, 0.0, 0.0, 0.0, round(p, 8), round(b, 8), tuple(reasons))

    full = (p * b - (1.0 - p)) / b
    if full <= 0:
        return KellySizingDecision(
            False,
            0.0,
            round(full, 8),
            0.0,
            round(p, 8),
            round(b, 8),
            ("KELLY_NEGATIVE_EDGE",),
        )
    used_fraction = min(full * max(0.0, cfg.fraction), max(0.0, cfg.max_equity_fraction))
    raw_notional = equity * used_fraction
    absolute_capped = min(raw_notional, max(0.0, cfg.max_notional_usdt))
    remaining = max(0.0, float(cfg.max_total_exposure_usdt) - exposure)
    notional = min(absolute_capped, remaining)
    if notional < cfg.min_notional_usdt:
        reasons.append("KELLY_NOTIONAL_BELOW_MINIMUM")
    return KellySizingDecision(
        accepted=not reasons,
        notional_usdt=round(notional if not reasons else 0.0, 8),
        full_kelly_fraction=round(full, 8),
        used_fraction=round(used_fraction, 8),
        win_probability=round(p, 8),
        win_loss_ratio=round(b, 8),
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


__all__ = ["KellySizerConfig", "KellySizingDecision", "kelly_size_paper"]
