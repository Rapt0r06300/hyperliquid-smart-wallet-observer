"""Proportional paper sizing for wallet-mirror candidates.

Inspired by copy-wallet repos, but local and paper-only: a leader's notional is
scaled by a copy ratio, then capped by wallet equity and absolute limits.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProportionalSizingConfig:
    copy_ratio: float = 0.05
    max_mirror_notional_usdt: float = 50.0
    max_equity_pct: float = 5.0
    min_notional_usdt: float = 5.0


@dataclass(frozen=True, slots=True)
class ProportionalSizingDecision:
    accepted: bool
    paper_notional_usdt: float
    leader_notional_usdt: float
    copy_ratio: float
    capped_by_absolute_limit: bool
    capped_by_equity: bool
    reason: str


def size_proportional_paper_notional(
    *,
    leader_size: float,
    leader_price: float,
    equity_usdt: float,
    config: ProportionalSizingConfig | None = None,
) -> ProportionalSizingDecision:
    cfg = config or ProportionalSizingConfig()
    leader_notional = abs(float(leader_size or 0.0)) * max(0.0, float(leader_price or 0.0))
    if leader_notional <= 0:
        return ProportionalSizingDecision(False, 0.0, 0.0, cfg.copy_ratio, False, False, "LEADER_NOTIONAL_INVALID")

    raw = leader_notional * max(0.0, float(cfg.copy_ratio))
    equity_cap = max(0.0, float(equity_usdt or 0.0)) * max(0.0, float(cfg.max_equity_pct)) / 100.0
    absolute_cap = max(0.0, float(cfg.max_mirror_notional_usdt))
    capped_absolute = raw > absolute_cap if absolute_cap > 0 else False
    after_absolute = min(raw, absolute_cap) if absolute_cap > 0 else raw
    capped_equity = after_absolute > equity_cap if equity_cap > 0 else True
    notional = min(after_absolute, equity_cap) if equity_cap > 0 else 0.0

    if notional < max(0.0, float(cfg.min_notional_usdt)):
        return ProportionalSizingDecision(
            False,
            round(notional, 8),
            round(leader_notional, 8),
            round(cfg.copy_ratio, 8),
            capped_absolute,
            capped_equity,
            "MIRROR_NOTIONAL_BELOW_MINIMUM",
        )
    return ProportionalSizingDecision(
        True,
        round(notional, 8),
        round(leader_notional, 8),
        round(cfg.copy_ratio, 8),
        capped_absolute,
        capped_equity,
        "MIRROR_SIZE_OK",
    )


__all__ = [
    "ProportionalSizingConfig",
    "ProportionalSizingDecision",
    "size_proportional_paper_notional",
]

