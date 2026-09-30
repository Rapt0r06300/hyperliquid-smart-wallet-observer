"""Tiered copy sizing: combine copy ratio, Kelly cap and signal strength."""

from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.risk.kelly_sizer import KellySizerConfig, kelly_size_paper
from hl_observer.risk.proportional_paper_sizer import ProportionalSizingConfig, size_proportional_paper_notional


@dataclass(frozen=True, slots=True)
class TieredCopySizingConfig:
    proportional: ProportionalSizingConfig = field(default_factory=ProportionalSizingConfig)
    kelly: KellySizerConfig = field(default_factory=KellySizerConfig)
    high_confidence_multiplier: float = 1.25
    medium_confidence_multiplier: float = 1.0
    low_confidence_multiplier: float = 0.5


@dataclass(frozen=True, slots=True)
class TieredCopySizingDecision:
    accepted: bool
    notional_usdt: float
    tier: str
    reason_codes: tuple[str, ...]
    proportional_notional_usdt: float
    kelly_notional_usdt: float


def tiered_copy_size(
    *,
    leader_size: float,
    leader_price: float,
    equity_usdt: float,
    current_exposure_usdt: float,
    confidence: float,
    win_probability: float,
    win_loss_ratio: float,
    config: TieredCopySizingConfig | None = None,
) -> TieredCopySizingDecision:
    cfg = config or TieredCopySizingConfig()
    prop = size_proportional_paper_notional(
        leader_size=leader_size,
        leader_price=leader_price,
        equity_usdt=equity_usdt,
        config=cfg.proportional,
    )
    kelly = kelly_size_paper(
        win_probability=win_probability,
        win_loss_ratio=win_loss_ratio,
        equity_usdt=equity_usdt,
        current_exposure_usdt=current_exposure_usdt,
        config=cfg.kelly,
    )
    reasons: list[str] = []
    if not prop.accepted:
        reasons.append(prop.reason)
    if not kelly.accepted:
        reasons.extend(kelly.reason_codes)
    if reasons:
        return TieredCopySizingDecision(
            False,
            0.0,
            "REJECT",
            tuple(dict.fromkeys(reasons)),
            prop.paper_notional_usdt,
            kelly.notional_usdt,
        )

    conf = max(0.0, min(1.0, float(confidence or 0.0)))
    if conf >= 0.80:
        tier = "HIGH"
        mult = cfg.high_confidence_multiplier
    elif conf >= 0.60:
        tier = "MEDIUM"
        mult = cfg.medium_confidence_multiplier
    else:
        tier = "LOW"
        mult = cfg.low_confidence_multiplier
    base = min(prop.paper_notional_usdt, kelly.notional_usdt)
    notional = max(0.0, min(cfg.proportional.max_mirror_notional_usdt, base * mult))
    if notional < cfg.proportional.min_notional_usdt:
        return TieredCopySizingDecision(
            False,
            0.0,
            tier,
            ("TIERED_NOTIONAL_BELOW_MINIMUM",),
            prop.paper_notional_usdt,
            kelly.notional_usdt,
        )
    return TieredCopySizingDecision(
        True,
        round(notional, 8),
        tier,
        (),
        prop.paper_notional_usdt,
        kelly.notional_usdt,
    )


__all__ = ["TieredCopySizingConfig", "TieredCopySizingDecision", "tiered_copy_size"]
