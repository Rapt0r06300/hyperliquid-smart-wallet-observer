from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256

from hl_observer.config.settings import Settings
from hl_observer.hyperliquid.schemas import RiskDecision, SignalDecision
from hl_observer.paper_trading.exec_model import ExecModelConfig, ExecResult, simulate_execution
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.risk.gates import RiskContext
from hl_observer.risk.risk_engine import RiskEngine
from hl_observer.signals.leader_delta import LeaderDelta


@dataclass(frozen=True, slots=True)
class PaperEngineConfig:
    starting_cash_usdt: float = 1_000.0
    max_position_usdt: float = 40.0          # MARGIN per position (capital deployed)
    max_total_exposure_usdt: float = 1_200.0  # total MARGIN cap (capital), not leveraged notional
    max_open_positions: int = 60
    leverage: float = 1.0                     # perp leverage: position notional = margin * leverage
    default_top_depth_usdt: float | None = None
    exec_model: ExecModelConfig = field(default_factory=ExecModelConfig)


@dataclass(frozen=True, slots=True)
class PaperPosition:
    position_id: str
    coin: str
    side: str  # LONG | SHORT
    quantity: float
    entry_price: float
    notional_usdt: float
    opened_at_ms: int
    source_delta_id: str
    leader_wallet: str


@dataclass(frozen=True, slots=True)
class PaperTrade:
    trade_id: str
    action: str  # OPEN | REDUCE | CLOSE | NO_TRADE
    coin: str
    side: str
    quantity: float
    fill_price: float | None
    notional_usdt: float
    realized_pnl_usdt: float
    fees_and_cost_bps: float
    source_delta_id: str
    reason_codes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class PaperDecisionResult:
    accepted: bool
    risk_decision: RiskDecision
    trade: PaperTrade | None
    position: PaperPosition | None
    cash_usdt: float
    equity_usdt: float
    realized_pnl_usdt: float
    unrealized_pnl_usdt: float
    drawdown_usdt: float
    reason_codes: tuple[str, ...]
    evidence_hash: str


class PaperEngine:
    """Local-only paper engine for V12 vertical slices.

    The engine mutates only in-memory simulated state. It never creates a venue
    order, never signs, and never calls an external endpoint.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        config: PaperEngineConfig | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.config = config or PaperEngineConfig()
        self._risk_engine = RiskEngine(self.settings)
        self.cash_usdt = float(self.config.starting_cash_usdt)
        self.realized_pnl_usdt = 0.0
        self._positions: dict[str, PaperPosition] = {}
        self._high_water_equity = self.cash_usdt

    @property
    def positions(self) -> tuple[PaperPosition, ...]:
        return tuple(self._positions.values())

    def apply_delta(
        self,
        delta: LeaderDelta,
        *,
        market_price: float,
        observed_at_ms: int,
        edge_remaining_bps: float,
        spread_bps: float,
        estimated_slippage_bps: float,
        top_depth_usdt: float | None,
        wallet_score: float,
        signal_score: float,
        marks: dict[str, float] | None = None,
    ) -> PaperDecisionResult:
        reasons: list[str] = list(delta.reason_codes)
        if market_price <= 0:
            reasons.append("MARKET_PRICE_INVALID")
        if not delta.safe_for_paper_candidate and not delta.is_exit_or_reduce:
            reasons.append("DELTA_NOT_SAFE_FOR_PAPER")

        risk_context = RiskContext(
            spread_bps=spread_bps,
            estimated_slippage_bps=estimated_slippage_bps,
            orderbook_depth_usdc=float(top_depth_usdt or 0.0),
            wallet_score=wallet_score,
            signal_score=signal_score,
            edge_remaining_bps=edge_remaining_bps,
            signal_age_ms=max(0, observed_at_ms - (delta.leader_event_time_ms or observed_at_ms)),
            data_gap=market_price <= 0,
        )
        risk_decision = self._risk_engine.evaluate(risk_context)
        if not risk_decision.allowed and not delta.is_exit_or_reduce:
            reasons.extend(risk_decision.reasons)

        if reasons or market_price <= 0:
            return self._result(
                accepted=False,
                risk_decision=risk_decision,
                trade=self._no_trade(delta, reasons),
                position=None,
                marks=marks or {delta.coin: market_price},
                reasons=reasons,
            )

        if delta.is_exit_or_reduce:
            return self._apply_exit_delta(delta, market_price=market_price, observed_at_ms=observed_at_ms, risk_decision=risk_decision, marks=marks)

        side = _side_for_entry(delta)
        if side is None:
            reasons.append("ENTRY_SIDE_UNKNOWN")
            return self._result(
                accepted=False,
                risk_decision=risk_decision,
                trade=self._no_trade(delta, reasons),
                position=None,
                marks=marks or {delta.coin: market_price},
                reasons=reasons,
            )
        if len(self._positions) >= self.config.max_open_positions:
            reasons.append("MAX_OPEN_POSITIONS_REACHED")
        if self._gross_exposure_usdt() >= self.config.max_total_exposure_usdt:
            reasons.append("MAX_TOTAL_EXPOSURE_REACHED")
        if reasons:
            return self._result(
                accepted=False,
                risk_decision=risk_decision,
                trade=self._no_trade(delta, reasons),
                position=None,
                marks=marks or {delta.coin: market_price},
                reasons=reasons,
            )

        # margin (capital deployed) is capped; the position controls margin*leverage of notional.
        margin = min(self.config.max_position_usdt, max(0.0, self.config.max_total_exposure_usdt - self._gross_exposure_usdt()))
        notional = margin * max(1.0, float(self.config.leverage))
        exec_result = simulate_execution(
            side=side,
            notional_usdc=notional,
            mid_price=market_price,
            top_depth_usdc=top_depth_usdt or self.config.default_top_depth_usdt,
            is_maker=False,
            config=self.config.exec_model,
        )
        quantity = notional / exec_result.fill_price
        position_id = _id("paperpos", delta.delta_id, delta.coin, side, observed_at_ms)
        position = PaperPosition(
            position_id=position_id,
            coin=delta.coin,
            side=side,
            quantity=quantity,
            entry_price=exec_result.fill_price,
            notional_usdt=notional,
            opened_at_ms=observed_at_ms,
            source_delta_id=delta.delta_id,
            leader_wallet=delta.wallet,
        )
        self._positions[position_id] = position
        trade = PaperTrade(
            trade_id=_id("papertrade", position_id, "OPEN"),
            action="OPEN",
            coin=delta.coin,
            side=side,
            quantity=quantity,
            fill_price=exec_result.fill_price,
            notional_usdt=notional,
            realized_pnl_usdt=0.0,
            fees_and_cost_bps=exec_result.net_cost_bps,
            source_delta_id=delta.delta_id,
        )
        return self._result(
            accepted=True,
            risk_decision=risk_decision,
            trade=trade,
            position=position,
            marks=marks or {delta.coin: market_price},
            reasons=(),
        )

    def mark_to_market(self, marks: dict[str, float]) -> tuple[float, float, float]:
        unrealized = sum(_position_unrealized(position, marks.get(position.coin, position.entry_price)) for position in self._positions.values())
        equity = self.cash_usdt + self.realized_pnl_usdt + unrealized
        self._high_water_equity = max(self._high_water_equity, equity)
        drawdown = max(0.0, self._high_water_equity - equity)
        return round(equity, 8), round(unrealized, 8), round(drawdown, 8)

    def _apply_exit_delta(
        self,
        delta: LeaderDelta,
        *,
        market_price: float,
        observed_at_ms: int,
        risk_decision: RiskDecision,
        marks: dict[str, float] | None,
    ) -> PaperDecisionResult:
        position = self._find_position_for_exit(delta)
        reasons: list[str] = []
        if position is None:
            reasons.append("NO_MATCHING_PAPER_POSITION_FOR_CLOSE")
            return self._result(False, risk_decision, self._no_trade(delta, reasons), None, marks or {delta.coin: market_price}, reasons)

        close_fraction = 1.0 if delta.action in {LifecycleAction.CLOSE_LONG, LifecycleAction.CLOSE_SHORT} else _reduce_fraction(position, delta)
        close_quantity = position.quantity * close_fraction
        close_notional = close_quantity * market_price
        exit_exec = simulate_execution(
            side="SELL" if position.side == "LONG" else "BUY",
            notional_usdc=close_notional,
            mid_price=market_price,
            top_depth_usdc=self.config.default_top_depth_usdt,
            is_maker=False,
            config=self.config.exec_model,
        )
        gross = _closed_pnl(position, close_quantity, exit_exec.fill_price)
        cost = close_notional * max(exit_exec.net_cost_bps, 0.0) / 10_000.0
        realized = gross - cost
        self.realized_pnl_usdt += realized
        remaining_quantity = position.quantity - close_quantity
        if remaining_quantity <= 1e-12:
            del self._positions[position.position_id]
        else:
            self._positions[position.position_id] = replace(
                position,
                quantity=remaining_quantity,
                notional_usdt=remaining_quantity * position.entry_price,
            )
        trade = PaperTrade(
            trade_id=_id("papertrade", position.position_id, "EXIT", observed_at_ms),
            action="CLOSE" if close_fraction >= 0.999 else "REDUCE",
            coin=position.coin,
            side=position.side,
            quantity=close_quantity,
            fill_price=exit_exec.fill_price,
            notional_usdt=close_notional,
            realized_pnl_usdt=realized,
            fees_and_cost_bps=exit_exec.net_cost_bps,
            source_delta_id=delta.delta_id,
        )
        return self._result(True, risk_decision, trade, self._positions.get(position.position_id), marks or {delta.coin: market_price}, ())

    def _find_position_for_exit(self, delta: LeaderDelta) -> PaperPosition | None:
        target_side = _side_for_exit(delta)
        for position in self._positions.values():
            if position.coin != delta.coin:
                continue
            if target_side is None or position.side == target_side:
                return position
        return None

    def _gross_exposure_usdt(self) -> float:
        # MARGIN terms (capital at risk): notional_usdt is leveraged, divide back by leverage.
        return sum(position.notional_usdt for position in self._positions.values()) / max(1.0, float(self.config.leverage))

    def _no_trade(self, delta: LeaderDelta, reasons: list[str] | tuple[str, ...]) -> PaperTrade:
        return PaperTrade(
            trade_id=_id("notrade", delta.delta_id),
            action="NO_TRADE",
            coin=delta.coin,
            side="NONE",
            quantity=0.0,
            fill_price=None,
            notional_usdt=0.0,
            realized_pnl_usdt=0.0,
            fees_and_cost_bps=0.0,
            source_delta_id=delta.delta_id,
            reason_codes=tuple(dict.fromkeys(reasons)),
        )

    def _result(
        self,
        accepted: bool,
        risk_decision: RiskDecision,
        trade: PaperTrade | None,
        position: PaperPosition | None,
        marks: dict[str, float],
        reasons: list[str] | tuple[str, ...],
    ) -> PaperDecisionResult:
        equity, unrealized, drawdown = self.mark_to_market(marks)
        payload = (
            accepted,
            getattr(risk_decision.decision, "value", str(risk_decision.decision)),
            tuple(reasons),
            trade.trade_id if trade else None,
            position.position_id if position else None,
            equity,
            self.realized_pnl_usdt,
            unrealized,
        )
        return PaperDecisionResult(
            accepted=accepted,
            risk_decision=risk_decision,
            trade=trade,
            position=position,
            cash_usdt=self.cash_usdt,
            equity_usdt=equity,
            realized_pnl_usdt=round(self.realized_pnl_usdt, 8),
            unrealized_pnl_usdt=unrealized,
            drawdown_usdt=drawdown,
            reason_codes=tuple(dict.fromkeys(reasons)),
            evidence_hash=_id("pevidence", *payload),
        )


def _side_for_entry(delta: LeaderDelta) -> str | None:
    if delta.action == LifecycleAction.OPEN_LONG:
        return "LONG"
    if delta.action == LifecycleAction.OPEN_SHORT:
        return "SHORT"
    if delta.action in {LifecycleAction.ADD, LifecycleAction.INCREASE}:
        if delta.current_size > 0:
            return "LONG"
        if delta.current_size < 0:
            return "SHORT"
    return None


def _side_for_exit(delta: LeaderDelta) -> str | None:
    if delta.action == LifecycleAction.CLOSE_LONG:
        return "LONG"
    if delta.action == LifecycleAction.CLOSE_SHORT:
        return "SHORT"
    if delta.action == LifecycleAction.REDUCE:
        if delta.previous_size > 0 or delta.current_size > 0:
            return "LONG"
        if delta.previous_size < 0 or delta.current_size < 0:
            return "SHORT"
    return None


def _position_unrealized(position: PaperPosition, mark: float) -> float:
    if position.side == "LONG":
        return (mark - position.entry_price) * position.quantity
    return (position.entry_price - mark) * position.quantity


def _closed_pnl(position: PaperPosition, quantity: float, exit_price: float) -> float:
    if position.side == "LONG":
        return (exit_price - position.entry_price) * quantity
    return (position.entry_price - exit_price) * quantity


def _reduce_fraction(position: PaperPosition, delta: LeaderDelta) -> float:
    previous_abs = abs(delta.previous_size)
    current_abs = abs(delta.current_size)
    if previous_abs <= 0 or current_abs >= previous_abs:
        return 1.0
    return max(0.0, min(1.0, (previous_abs - current_abs) / previous_abs))


def _id(prefix: str, *parts: object) -> str:
    material = "|".join(str(part) for part in parts)
    return prefix + ":" + sha256(material.encode("utf-8")).hexdigest()[:24]


__all__ = [
    "PaperDecisionResult",
    "PaperEngine",
    "PaperEngineConfig",
    "PaperPosition",
    "PaperTrade",
]
