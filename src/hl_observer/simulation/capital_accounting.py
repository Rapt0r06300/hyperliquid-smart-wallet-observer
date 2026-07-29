"""Explicit capital, margin, exposure and ROI semantics for paper trading."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class PositionCapitalInput:
    position_id: str
    leg_notional_usd: tuple[float, ...]
    leg_direction: tuple[int, ...]
    leverage_effective: float
    unrealized_mid_pnl_usd: float
    liquidatable_pnl_usd: float | None
    liquidation_buffer_bps: float | None = None

    def __post_init__(self) -> None:
        if not self.position_id:
            raise ValueError("position_id is required")
        if not self.leg_notional_usd:
            raise ValueError("at least one leg notional is required")
        if len(self.leg_notional_usd) != len(self.leg_direction):
            raise ValueError("leg notional and direction lengths differ")
        if any(not _finite_positive(value) for value in self.leg_notional_usd):
            raise ValueError("leg notionals must be finite and positive")
        if any(direction not in {-1, 1} for direction in self.leg_direction):
            raise ValueError("leg directions must be -1 or 1")
        if not _finite_positive(self.leverage_effective):
            raise ValueError("leverage_effective must be finite and positive")
        if not _finite(self.unrealized_mid_pnl_usd):
            raise ValueError("unrealized_mid_pnl_usd must be finite")
        if self.liquidatable_pnl_usd is not None and not _finite(
            self.liquidatable_pnl_usd
        ):
            raise ValueError("liquidatable_pnl_usd must be finite or None")
        if self.liquidation_buffer_bps is not None and not _finite(
            self.liquidation_buffer_bps
        ):
            raise ValueError("liquidation_buffer_bps must be finite or None")

    @property
    def gross_exposure_usd(self) -> float:
        return sum(abs(value) for value in self.leg_notional_usd)

    @property
    def net_directional_exposure_usd(self) -> float:
        return sum(
            value * direction
            for value, direction in zip(
                self.leg_notional_usd,
                self.leg_direction,
                strict=True,
            )
        )

    @property
    def margin_locked_usd(self) -> float:
        return self.gross_exposure_usd / self.leverage_effective


@dataclass(frozen=True, slots=True)
class CapitalAccountingSnapshot:
    starting_equity_usd: float
    free_cash_usd: float
    margin_locked_usd: float
    gross_exposure_usd: float
    net_directional_exposure_usd: float
    leg_notional_usd: tuple[float, ...]
    leverage_effective: float | None
    liquidation_buffer_bps: float | None
    realized_pnl_usd: float
    unrealized_mid_pnl_usd: float
    liquidatable_pnl_usd: float | None
    mid_equity_usd: float
    liquidatable_equity_usd: float | None
    turnover_usd: float
    avg_margin_locked_usd: float
    peak_margin_locked_usd: float
    ROI_starting_equity: float | None
    ROI_avg_margin_locked: float | None
    ROI_peak_margin_locked: float | None
    return_on_gross_exposure: float | None
    roi_status: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["leg_notional_usd"] = list(self.leg_notional_usd)
        return payload


class CapitalAccountingTracker:
    """Track comparable paper-capital denominators across observations."""

    def __init__(self, *, starting_equity_usd: float) -> None:
        if not _finite_positive(starting_equity_usd):
            raise ValueError("starting_equity_usd must be finite and positive")
        self.starting_equity_usd = float(starting_equity_usd)
        self._margin_sum = 0.0
        self._margin_observations = 0
        self._peak_margin = 0.0
        self._last_observed_margin: float | None = None
        self._latest: CapitalAccountingSnapshot | None = None

    @property
    def latest(self) -> CapitalAccountingSnapshot | None:
        return self._latest

    def observe(
        self,
        *,
        collateral_cash_usd: float,
        positions: tuple[PositionCapitalInput, ...],
        realized_pnl_usd: float,
        turnover_usd: float,
    ) -> CapitalAccountingSnapshot:
        for name, value in (
            ("collateral_cash_usd", collateral_cash_usd),
            ("realized_pnl_usd", realized_pnl_usd),
            ("turnover_usd", turnover_usd),
        ):
            if not _finite(value):
                raise ValueError(f"{name} must be finite")
        gross = sum(position.gross_exposure_usd for position in positions)
        net = sum(position.net_directional_exposure_usd for position in positions)
        margin = sum(position.margin_locked_usd for position in positions)
        mid_pnl = sum(position.unrealized_mid_pnl_usd for position in positions)
        liquidatable_known = all(
            position.liquidatable_pnl_usd is not None for position in positions
        )
        liquidatable_pnl = (
            sum(float(position.liquidatable_pnl_usd or 0.0) for position in positions)
            if liquidatable_known
            else None
        )
        # Average active margin is sampled only on capital state changes. It is
        # therefore deterministic and does not change when the UI or mark loop
        # polls more frequently.
        if margin > 0 and (
            self._last_observed_margin is None
            or not math.isclose(
                margin,
                self._last_observed_margin,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        ):
            self._margin_observations += 1
            self._margin_sum += margin
            self._last_observed_margin = margin
        self._peak_margin = max(self._peak_margin, margin)
        average_margin = (
            self._margin_sum / self._margin_observations
            if self._margin_observations
            else 0.0
        )
        liquidatable_equity = (
            float(collateral_cash_usd) + liquidatable_pnl
            if liquidatable_pnl is not None
            else None
        )
        authoritative_pnl = (
            liquidatable_equity - self.starting_equity_usd
            if liquidatable_equity is not None
            else None
        )
        buffers = [
            float(position.liquidation_buffer_bps)
            for position in positions
            if position.liquidation_buffer_bps is not None
        ]
        snapshot = CapitalAccountingSnapshot(
            starting_equity_usd=round(self.starting_equity_usd, 10),
            free_cash_usd=round(float(collateral_cash_usd) - margin, 10),
            margin_locked_usd=round(margin, 10),
            gross_exposure_usd=round(gross, 10),
            net_directional_exposure_usd=round(net, 10),
            leg_notional_usd=tuple(
                round(value, 10)
                for position in positions
                for value in position.leg_notional_usd
            ),
            leverage_effective=(
                round(gross / margin, 10) if margin > 0 else None
            ),
            liquidation_buffer_bps=min(buffers) if len(buffers) == len(positions) and buffers else None,
            realized_pnl_usd=round(float(realized_pnl_usd), 10),
            unrealized_mid_pnl_usd=round(mid_pnl, 10),
            liquidatable_pnl_usd=(
                round(liquidatable_pnl, 10)
                if liquidatable_pnl is not None
                else None
            ),
            mid_equity_usd=round(float(collateral_cash_usd) + mid_pnl, 10),
            liquidatable_equity_usd=(
                round(liquidatable_equity, 10)
                if liquidatable_equity is not None
                else None
            ),
            turnover_usd=round(float(turnover_usd), 10),
            avg_margin_locked_usd=round(average_margin, 10),
            peak_margin_locked_usd=round(self._peak_margin, 10),
            ROI_starting_equity=_ratio(
                authoritative_pnl,
                self.starting_equity_usd,
            ),
            ROI_avg_margin_locked=_ratio(
                authoritative_pnl,
                average_margin,
            ),
            ROI_peak_margin_locked=_ratio(
                authoritative_pnl,
                self._peak_margin,
            ),
            return_on_gross_exposure=_ratio(
                authoritative_pnl,
                gross,
            ),
            roi_status=(
                "LIQUIDATABLE_EXECUTABLE"
                if authoritative_pnl is not None
                else "UNMEASURABLE_NO_EXECUTABLE_EXIT"
            ),
        )
        self._latest = snapshot
        return snapshot


def _ratio(numerator: float | None, denominator: float) -> float | None:
    if numerator is None or denominator <= 0:
        return None
    return round(numerator / denominator, 10)


def _finite(value: object) -> bool:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(parsed)


def _finite_positive(value: object) -> bool:
    return _finite(value) and float(value) > 0


__all__ = [
    "CapitalAccountingSnapshot",
    "CapitalAccountingTracker",
    "PositionCapitalInput",
]
