from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from hyper_smart_observer.backtesting.backtest_report import BacktestReport
from hyper_smart_observer.backtesting.execution_delay_model import delay_penalty_bps
from hyper_smart_observer.copy_mode.copy_models import DeltaAction, LeaderDelta


@dataclass(frozen=True)
class HistoricalPricePoint:
    """Observed market point used by deterministic local replay.

    ``available_notional`` is optional. When provided it caps the simulated
    notional at this observation and therefore makes partial/missed fills
    explicit instead of silently assuming infinite liquidity.
    """

    coin: str
    ts_ms: int
    mid: float
    available_notional: float | None = None

    def __post_init__(self) -> None:
        if self.ts_ms < 0:
            raise ValueError("ts_ms must be non-negative")
        if self.mid <= 0:
            raise ValueError("mid must be positive")
        if self.available_notional is not None and self.available_notional < 0:
            raise ValueError("available_notional must be non-negative")


@dataclass(frozen=True)
class ReplayScenario:
    name: str
    delay_ms: int
    fee_bps: float = 5.0
    spread_bps: float = 2.0
    slippage_bps: float = 5.0
    latency_bps_per_second: float = 0.0
    max_price_age_ms: int = 30_000

    def __post_init__(self) -> None:
        if self.delay_ms < 0:
            raise ValueError("delay_ms must be non-negative")
        if self.max_price_age_ms < 0:
            raise ValueError("max_price_age_ms must be non-negative")
        for name, value in (
            ("fee_bps", self.fee_bps),
            ("spread_bps", self.spread_bps),
            ("slippage_bps", self.slippage_bps),
            ("latency_bps_per_second", self.latency_bps_per_second),
        ):
            if value < 0:
                raise ValueError(f"{name} must be non-negative")

    @property
    def delay_cost_bps(self) -> float:
        return delay_penalty_bps(self.delay_ms, bps_per_second=self.latency_bps_per_second)


@dataclass(frozen=True)
class DeltaReplayTrade:
    wallet_address: str
    coin: str
    direction: str
    entry_mid: float
    exit_mid: float
    closed_notional: float
    gross_pnl: float
    exit_ts_ms: int
    trigger: str


@dataclass(frozen=True)
class DeltaReplayReport:
    scenario: str
    requested_actions: int
    simulated_actions: int
    skipped_actions: int
    missed_fills: int
    partial_fills: int
    closed_trades: int
    gross_pnl: float
    total_costs: float
    net_pnl: float
    max_drawdown: float
    equity_curve: list[float]
    cost_breakdown: dict[str, float]
    no_trade_reasons: dict[str, int]
    trades: list[DeltaReplayTrade] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    disclaimer: str = "local delta replay only; historical simulation is not future profit"

    def to_backtest_report(self, wallet_address: str = "MULTI") -> BacktestReport:
        return BacktestReport(
            wallet_address=wallet_address,
            scenario=self.scenario,
            simulated_trades=self.closed_trades,
            skipped_actions=self.skipped_actions,
            net_pnl=self.net_pnl,
            max_drawdown=self.max_drawdown,
            warnings=list(self.warnings),
            gross_pnl=self.gross_pnl,
            total_costs=self.total_costs,
            equity_curve=list(self.equity_curve),
            cost_breakdown=dict(self.cost_breakdown),
        )


@dataclass
class _PositionState:
    direction: int
    entry_mid: float
    notional: float


class _PriceIndex:
    def __init__(self, points: Iterable[HistoricalPricePoint]) -> None:
        grouped: dict[str, list[HistoricalPricePoint]] = {}
        for point in points:
            grouped.setdefault(point.coin.upper(), []).append(point)
        self._points: dict[str, list[HistoricalPricePoint]] = {}
        self._times: dict[str, list[int]] = {}
        for coin, values in grouped.items():
            ordered = sorted(values, key=lambda item: item.ts_ms)
            self._points[coin] = ordered
            self._times[coin] = [item.ts_ms for item in ordered]

    def at_or_after(self, coin: str, target_ms: int, max_age_ms: int) -> HistoricalPricePoint | None:
        key = coin.upper()
        times = self._times.get(key)
        if not times:
            return None
        idx = bisect_left(times, target_ms)
        if idx >= len(times):
            return None
        point = self._points[key][idx]
        if point.ts_ms - target_ms > max_age_ms:
            return None
        return point


def build_standard_delay_scenarios(
    *,
    ws_delay_ms: int = 250,
    fee_bps: float = 5.0,
    spread_bps: float = 2.0,
    slippage_bps: float = 5.0,
    latency_bps_per_second: float = 0.0,
    max_price_age_ms: int = 30_000,
) -> list[ReplayScenario]:
    """Return the three required copy-delay scenarios: WS, 60 s and 5 min."""

    common = dict(
        fee_bps=fee_bps,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        latency_bps_per_second=latency_bps_per_second,
        max_price_age_ms=max_price_age_ms,
    )
    return [
        ReplayScenario("ws", ws_delay_ms, **common),
        ReplayScenario("delay_60s", 60_000, **common),
        ReplayScenario("delay_5m", 300_000, **common),
    ]


def replay_leader_deltas(
    deltas: Iterable[LeaderDelta],
    prices: Iterable[HistoricalPricePoint],
    scenario: ReplayScenario,
    *,
    notional_per_entry: float = 50.0,
) -> DeltaReplayReport:
    """Replay historical LeaderDelta objects against observed market prices.

    The engine is deliberately deterministic and local-only. It refuses an
    action when the delayed market observation is unavailable, refuses
    ambiguous/UNKNOWN deltas, never treats open orders as fills, applies costs
    on every simulated action, and records partial fills when observed
    liquidity is bounded.
    """

    if notional_per_entry <= 0:
        raise ValueError("notional_per_entry must be positive")

    ordered = sorted(list(deltas), key=_delta_ts_ms)
    price_index = _PriceIndex(prices)
    positions: dict[tuple[str, str], _PositionState] = {}
    cost_breakdown = {"fees": 0.0, "spread": 0.0, "slippage": 0.0, "latency": 0.0}
    no_trade: dict[str, int] = {}
    warnings: list[str] = []
    trades: list[DeltaReplayTrade] = []
    equity_curve = [0.0]
    gross_pnl = 0.0
    total_costs = 0.0
    simulated_actions = 0
    missed_fills = 0
    partial_fills = 0

    def reject(reason: str) -> None:
        no_trade[reason] = no_trade.get(reason, 0) + 1

    def charge_costs(notional: float) -> float:
        nonlocal total_costs
        components = {
            "fees": notional * scenario.fee_bps / 10_000.0,
            # spread_bps represents full quoted width; crossing from mid pays half.
            "spread": notional * (scenario.spread_bps / 2.0) / 10_000.0,
            "slippage": notional * scenario.slippage_bps / 10_000.0,
            "latency": notional * scenario.delay_cost_bps / 10_000.0,
        }
        action_cost = sum(components.values())
        total_costs += action_cost
        for name, value in components.items():
            cost_breakdown[name] += value
        return action_cost

    for delta in ordered:
        action = delta.action_type
        key = (delta.leader_wallet.lower(), delta.coin.upper())
        signal_ts = _delta_ts_ms(delta)
        target_ts = signal_ts + scenario.delay_ms
        point = price_index.at_or_after(delta.coin, target_ts, scenario.max_price_age_ms)

        if action == DeltaAction.UNKNOWN:
            reject("UNKNOWN_DELTA")
            continue
        if point is None:
            missed_fills += 1
            reject("MISSED_FILL_NO_DELAYED_PRICE")
            continue

        if action in {DeltaAction.OPEN_LONG, DeltaAction.OPEN_SHORT, DeltaAction.ADD, DeltaAction.INCREASE}:
            direction = _entry_direction(delta)
            if direction == 0:
                reject("ENTRY_DIRECTION_UNMEASURABLE")
                continue
            existing = positions.get(key)
            if existing is not None and existing.direction != direction:
                reject("POSITION_FLIP_UNSUPPORTED")
                continue
            desired_notional = notional_per_entry
            filled_notional, is_partial = _fill_notional(desired_notional, point.available_notional)
            if filled_notional <= 0:
                missed_fills += 1
                reject("MISSED_FILL_NO_LIQUIDITY")
                continue
            if is_partial:
                partial_fills += 1
            charge_costs(filled_notional)
            if existing is None:
                positions[key] = _PositionState(direction=direction, entry_mid=point.mid, notional=filled_notional)
            else:
                combined = existing.notional + filled_notional
                existing.entry_mid = ((existing.entry_mid * existing.notional) + (point.mid * filled_notional)) / combined
                existing.notional = combined
            simulated_actions += 1
            equity_curve.append(gross_pnl - total_costs)
            continue

        if action not in {DeltaAction.REDUCE, DeltaAction.CLOSE_LONG, DeltaAction.CLOSE_SHORT}:
            reject("UNSUPPORTED_DELTA_ACTION")
            continue

        existing = positions.get(key)
        if existing is None:
            reject("NO_MATCHING_PAPER_POSITION_FOR_CLOSE")
            continue
        close_fraction = _close_fraction(delta)
        if close_fraction is None or close_fraction <= 0:
            reject("REDUCE_FRACTION_UNMEASURABLE")
            continue
        desired_notional = existing.notional * close_fraction
        filled_notional, is_partial = _fill_notional(desired_notional, point.available_notional)
        if filled_notional <= 0:
            missed_fills += 1
            reject("MISSED_FILL_NO_LIQUIDITY")
            continue
        if is_partial:
            partial_fills += 1
        charge_costs(filled_notional)
        realized = existing.direction * (point.mid - existing.entry_mid) * (filled_notional / existing.entry_mid)
        gross_pnl += realized
        existing.notional = max(0.0, existing.notional - filled_notional)
        trades.append(
            DeltaReplayTrade(
                wallet_address=delta.leader_wallet,
                coin=delta.coin.upper(),
                direction="LONG" if existing.direction > 0 else "SHORT",
                entry_mid=existing.entry_mid,
                exit_mid=point.mid,
                closed_notional=filled_notional,
                gross_pnl=realized,
                exit_ts_ms=point.ts_ms,
                trigger=action.value,
            )
        )
        if existing.notional <= 1e-9:
            positions.pop(key, None)
        simulated_actions += 1
        equity_curve.append(gross_pnl - total_costs)

    net_pnl = gross_pnl - total_costs
    max_drawdown = _max_drawdown(equity_curve)
    skipped = len(ordered) - simulated_actions
    if positions:
        warnings.append(f"open_positions_unrealized:{len(positions)}")
    if scenario.delay_ms and scenario.latency_bps_per_second == 0:
        warnings.append("latency_price_effect_is_captured_by_delayed_market_point; explicit_latency_bps=0")

    return DeltaReplayReport(
        scenario=scenario.name,
        requested_actions=len(ordered),
        simulated_actions=simulated_actions,
        skipped_actions=skipped,
        missed_fills=missed_fills,
        partial_fills=partial_fills,
        closed_trades=len(trades),
        gross_pnl=gross_pnl,
        total_costs=total_costs,
        net_pnl=net_pnl,
        max_drawdown=max_drawdown,
        equity_curve=equity_curve,
        cost_breakdown=cost_breakdown,
        no_trade_reasons=no_trade,
        trades=trades,
        warnings=warnings,
    )


def _delta_ts_ms(delta: LeaderDelta) -> int:
    value: datetime = delta.leader_fill_time or delta.observed_at
    return int(value.timestamp() * 1000)


def _entry_direction(delta: LeaderDelta) -> int:
    if delta.action_type == DeltaAction.OPEN_LONG:
        return 1
    if delta.action_type == DeltaAction.OPEN_SHORT:
        return -1
    for size in (delta.current_size, delta.previous_size):
        if size is not None and abs(size) > 1e-12:
            return 1 if size > 0 else -1
    return 0


def _close_fraction(delta: LeaderDelta) -> float | None:
    if delta.action_type in {DeltaAction.CLOSE_LONG, DeltaAction.CLOSE_SHORT}:
        return 1.0
    if delta.action_type != DeltaAction.REDUCE:
        return None
    if delta.previous_size is None or delta.current_size is None:
        return None
    previous = abs(delta.previous_size)
    current = abs(delta.current_size)
    if previous <= 1e-12 or current >= previous:
        return None
    return min(1.0, max(0.0, (previous - current) / previous))


def _fill_notional(desired: float, available: float | None) -> tuple[float, bool]:
    if available is None:
        return desired, False
    filled = min(desired, available)
    return filled, filled + 1e-12 < desired


def _max_drawdown(equity_curve: Iterable[float]) -> float:
    peak = float("-inf")
    max_dd = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        max_dd = max(max_dd, peak - value)
    return max_dd


__all__ = [
    "DeltaReplayReport",
    "DeltaReplayTrade",
    "HistoricalPricePoint",
    "ReplayScenario",
    "build_standard_delay_scenarios",
    "replay_leader_deltas",
]
