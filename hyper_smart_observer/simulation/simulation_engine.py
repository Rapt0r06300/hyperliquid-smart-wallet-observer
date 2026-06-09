from __future__ import annotations

from dataclasses import dataclass, field

from hyper_smart_observer.simulation.simulation_costs import apply_spread_and_slippage, fee_for_notional
from hl_observer.utils.simulation_utils import calculate_gross_pnl, get_exit_price
from hyper_smart_observer.simulation.simulation_models import (
    SimulationAction,
    SimulationConfig,
    SimulationDecision,
    SimulationFill,
    SimulationIntent,
    SimulationRunMode,
    SimulationSide,
    SimulationSourceQuality,
)
from hyper_smart_observer.simulation.virtual_portfolio import VirtualPortfolio
from hyper_smart_observer.simulation.virtual_position import VirtualPosition
from hl_observer.utils.time import now_ms


@dataclass(slots=True)
class SimulationEngine:
    config: SimulationConfig = field(default_factory=SimulationConfig)
    hard_max_signal_age_ms: int = 8000
    portfolio: VirtualPortfolio = field(init=False)
    fills: list[SimulationFill] = field(default_factory=list)
    decisions: list[SimulationDecision] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.portfolio = VirtualPortfolio(
            starting_equity=self.config.starting_equity,
            cash=self.config.starting_equity,
        )

    def apply(self, intent: SimulationIntent) -> SimulationDecision:
        if intent.coin and any(t in intent.coin.upper() for t in ("CASH:", "XYZ:", "@", "HYNA:", "FLX:", "KM:", "VNTL:")):
             return self._reject("COIN_BLACKLISTED", f"Coin {intent.coin} is blacklisted or exotic.")

        if intent.run_mode == SimulationRunMode.LIVE:
            age_ms = now_ms() - intent.observed_at_ms
            if age_ms > self.hard_max_signal_age_ms:
                 return self._reject("HARD_STALE_SIGNAL", f"Signal age {age_ms}ms exceeds limit {self.hard_max_signal_age_ms}ms.")

        if intent.reference_price <= 0:
            return self._reject("PRICE_INVALID", "Reference price must be positive.")
        if intent.requested_notional <= 0:
            return self._reject("NOTIONAL_INVALID", "Requested notional must be positive.")
        if intent.action == SimulationAction.OPEN:
            return self._open(intent)
        if intent.action in {SimulationAction.REDUCE, SimulationAction.CLOSE}:
            return self._reduce_or_close(intent)
        return self._reject("UNKNOWN_ACTION", "Unknown simulation action.")

    def _open(self, intent: SimulationIntent) -> SimulationDecision:
        if len(self.portfolio.positions) >= self.config.max_open_positions:
            return self._reject("MAX_OPEN_POSITIONS_REACHED", "Maximum open virtual positions reached.")
        notional = min(intent.requested_notional, self.config.max_position_notional)
        remaining = self.config.max_total_exposure - self.portfolio.open_exposure
        if remaining <= 0:
            return self._reject("MAX_TOTAL_EXPOSURE_REACHED", "Maximum total virtual exposure reached.")
        notional = min(notional, remaining)
        fill_ratio = max(0.0, min(1.0, self.config.partial_fill_ratio))
        if fill_ratio <= 0:
            return self._reject("MISSED_FILL", "Partial fill ratio is zero; simulated fill missed.")
        notional *= fill_ratio
        price = apply_spread_and_slippage(intent.reference_price, intent.side, self.config.spread_bps, self.config.slippage_bps)
        fee = fee_for_notional(notional, self.config.fee_bps)
        size = notional / price
        position_id = self._position_id(intent)
        self.portfolio.positions[position_id] = VirtualPosition(
            position_id=position_id,
            wallet_address=intent.wallet_address,
            coin=intent.coin,
            side=intent.side,
            entry_price=price,
            size=size,
            notional=notional,
            opened_at_ms=intent.observed_at_ms + self.config.latency_ms,
            fees_paid=fee,
        )
        self.portfolio.total_fees += fee
        self.fills.append(
            SimulationFill(
                fill_id=f"{intent.signal_id}:open",
                coin=intent.coin,
                side=intent.side,
                action=SimulationAction.OPEN,
                price=price,
                size=size,
                notional=notional,
                fee=fee,
                timestamp_ms=intent.observed_at_ms + self.config.latency_ms,
            )
        )
        self.portfolio.snapshot(intent.observed_at_ms + self.config.latency_ms, {intent.coin: intent.reference_price})
        return self._accept("OPENED_VIRTUAL_POSITION", "Opened local virtual position. No order was created.")

    def _reduce_or_close(self, intent: SimulationIntent) -> SimulationDecision:
        position_id = self._position_id(intent)
        position = self.portfolio.positions.get(position_id)
        if position is None:
            return self._reject("NO_MATCHING_VIRTUAL_POSITION", "No matching local virtual position exists for this close/reduce.")

        exit_price = get_exit_price(intent.reference_price, position.side.value, self.config.spread_bps, self.config.slippage_bps)

        close_notional = position.notional if intent.action == SimulationAction.CLOSE else min(position.notional, intent.requested_notional)
        close_ratio = min(1.0, close_notional / position.notional) if position.notional > 0 else 1.0
        closing_size = position.size * close_ratio
        gross_pnl = calculate_gross_pnl(position.side.value, position.entry_price, exit_price, closing_size)
        fee = fee_for_notional(close_notional, self.config.fee_bps)
        net_pnl = gross_pnl - fee
        # realized_pnl in VirtualPortfolio should ideally track gross realized,
        # while current_equity handles the total fees.
        # This matches the existing test expectation.
        self.portfolio.realized_pnl += gross_pnl
        self.portfolio.total_fees += fee
        position.notional -= close_notional
        position.size -= closing_size
        position.realized_pnl += gross_pnl
        self.fills.append(
            SimulationFill(
                fill_id=f"{intent.signal_id}:{intent.action.value.lower()}",
                coin=intent.coin,
                side=position.side,
                action=intent.action,
                price=exit_price,
                size=closing_size,
                notional=close_notional,
                fee=fee,
                timestamp_ms=intent.observed_at_ms + self.config.latency_ms,
                realized_pnl=net_pnl,
            )
        )
        if intent.action == SimulationAction.CLOSE or position.notional <= 1e-9 or position.size <= 1e-12:
            self.portfolio.positions.pop(position_id, None)
        self.portfolio.snapshot(intent.observed_at_ms + self.config.latency_ms, {intent.coin: intent.reference_price})
        return self._accept("UPDATED_VIRTUAL_POSITION", "Updated local virtual position. No order was created.")

    def _position_id(self, intent: SimulationIntent) -> str:
        return f"{intent.wallet_address.lower()}|{intent.coin.upper()}|{intent.side.value}"

    def _accept(self, reason: str, message: str) -> SimulationDecision:
        decision = SimulationDecision(True, reason, message)
        self.decisions.append(decision)
        return decision

    def _reject(self, reason: str, message: str) -> SimulationDecision:
        decision = SimulationDecision(False, reason, message)
        self.decisions.append(decision)
        return decision
