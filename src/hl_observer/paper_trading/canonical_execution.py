"""Canonical local paper-execution contract.

Every strategy lane may keep its own signal and position store, but the
translation from a risk-approved paper intent to an observable fill must pass
through this module.  The module is deliberately pure: it has no network
client, signer, key handling, or venue-order surface.

The accounting fields that require an existing position (realized PnL,
margin, equity) are emitted as explicit pending mutations.  The canonical
ledger applies them after it has the relevant position state; this module
never invents an account value.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from hashlib import sha256

from hl_observer.paper_trading.exec_model import ExecModelConfig, ExecResult, simulate_execution
from hl_observer.paper_trading.execution_truth import ExecutionTruth
from hl_observer.paper_trading.liquidity_consumption import (
    LiquidityConsumptionLedger,
    LiquidityReservation,
)


@dataclass(frozen=True, slots=True)
class PaperExecutionIntent:
    """Risk-approved, low-level paper intent consumed by the fill core."""

    strategy_id: str
    coin: str
    position_side: str
    action: str
    target_notional_usdc: float
    created_at_ms: int
    confidence: float = 0.0
    reasons: tuple[str, ...] = ()
    simulation_only: bool = True

    def __post_init__(self) -> None:
        side = str(self.position_side or "").strip().upper()
        action = str(self.action or "").strip().upper()
        coin = str(self.coin or "").strip().upper()
        strategy = str(self.strategy_id or "").strip()
        if self.simulation_only is not True:
            raise ValueError("canonical intent is paper-only")
        if not strategy or not coin:
            raise ValueError("strategy_id and coin are required")
        if side not in {"LONG", "SHORT"}:
            raise ValueError("position_side must be LONG or SHORT")
        if action not in {"OPEN", "ADD", "REDUCE", "CLOSE"}:
            raise ValueError("unsupported paper action")
        target = float(self.target_notional_usdc)
        if not math.isfinite(target) or target <= 0:
            raise ValueError("target_notional_usdc must be finite and positive")
        if int(self.created_at_ms) <= 0:
            raise ValueError("created_at_ms must be positive")
        object.__setattr__(self, "strategy_id", strategy)
        object.__setattr__(self, "coin", coin)
        object.__setattr__(self, "position_side", side)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "target_notional_usdc", target)
        object.__setattr__(self, "created_at_ms", int(self.created_at_ms))


@dataclass(frozen=True, slots=True)
class CausalMarketSnapshot:
    """The exact market observation available to one paper decision."""

    coin: str
    reference_mid: float
    decision_ts_ms: int
    execution_truth: ExecutionTruth | None
    source: str

    def __post_init__(self) -> None:
        coin = str(self.coin or "").strip().upper()
        source = str(self.source or "").strip()
        mid = float(self.reference_mid)
        decision_ts = int(self.decision_ts_ms)
        if not coin:
            raise ValueError("market snapshot coin is required")
        if not source:
            raise ValueError("market snapshot source is required")
        if not math.isfinite(mid) or mid <= 0:
            raise ValueError("reference_mid must be finite and positive")
        if decision_ts <= 0:
            raise ValueError("decision_ts_ms must be positive")
        if self.execution_truth is not None and self.execution_truth.coin != coin:
            raise ValueError("execution truth coin mismatch")
        object.__setattr__(self, "coin", coin)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "reference_mid", mid)
        object.__setattr__(self, "decision_ts_ms", decision_ts)

    @classmethod
    def from_truth(
        cls,
        truth: ExecutionTruth,
        *,
        decision_ts_ms: int,
    ) -> CausalMarketSnapshot:
        return cls(
            coin=truth.coin,
            reference_mid=truth.mid_price,
            decision_ts_ms=int(decision_ts_ms),
            execution_truth=truth,
            source=truth.source,
        )

    @property
    def snapshot_id(self) -> str:
        if self.execution_truth is not None:
            return self.execution_truth.snapshot_id
        material = repr(
            (
                self.coin,
                self.reference_mid,
                self.decision_ts_ms,
                self.source,
                "NO_EXECUTION_TRUTH",
            )
        )
        return "market-compat:" + sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    plan_id: str
    intent_id: str
    strategy_id: str
    coin: str
    action: str
    position_side: str
    execution_side: str
    requested_notional_usdc: float
    decision_ts_ms: int
    snapshot_id: str
    strict_book: bool
    paper_only: bool = True
    real_execution: bool = False


@dataclass(frozen=True, slots=True)
class PositionMutation:
    action: str
    position_side: str
    quantity_delta: float
    filled_notional_usdc: float
    fill_price: float | None
    status: str


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    event_id: str
    event_type: str
    plan_id: str
    strategy_id: str
    coin: str
    position_side: str
    execution_side: str
    requested_notional_usdc: float
    filled_notional_usdc: float
    missed_notional_usdc: float
    fill_price: float | None
    fee_bps: float | None
    slippage_bps: float | None
    latency_bps: float
    execution_snapshot_id: str | None
    cost_status: str
    reason: str
    paper_only: bool = True
    real_execution: bool = False


@dataclass(frozen=True, slots=True)
class EquityEvent:
    event_id: str
    plan_id: str
    filled_notional_usdc: float
    realized_pnl_delta_usdc: float | None
    accounting_status: str


@dataclass(frozen=True, slots=True)
class CanonicalExecutionResult:
    plan: ExecutionPlan
    execution: ExecResult
    position_mutation: PositionMutation
    ledger_event: LedgerEvent
    equity_event: EquityEvent
    liquidity_reservation: LiquidityReservation | None = None

    @property
    def accepted(self) -> bool:
        return (
            self.execution.fill_price is not None
            and self.execution.filled_notional_usdc > 0
            and not self.execution.missed
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "plan": asdict(self.plan),
            "execution": asdict(self.execution),
            "position_mutation": asdict(self.position_mutation),
            "ledger_event": asdict(self.ledger_event),
            "equity_event": asdict(self.equity_event),
            "liquidity_reservation": (
                asdict(self.liquidity_reservation)
                if self.liquidity_reservation is not None
                else None
            ),
            "paper_only": True,
            "real_execution": False,
        }


def build_execution_plan(
    intent: PaperExecutionIntent,
    market: CausalMarketSnapshot,
    *,
    strict_book: bool,
) -> ExecutionPlan:
    """Translate one strategy intent into an idempotent execution plan."""

    if intent.simulation_only is not True:
        raise ValueError("canonical execution accepts paper intents only")
    if intent.action not in {"OPEN", "ADD", "REDUCE", "CLOSE"}:
        raise ValueError("paper intent action is not executable")
    requested = float(intent.target_notional_usdc)
    if not math.isfinite(requested) or requested <= 0:
        raise ValueError("target_notional_usdc must be finite and positive")
    if str(intent.coin or "").strip().upper() != market.coin:
        raise ValueError("paper intent coin does not match market snapshot")
    execution_side = execution_side_for(intent.position_side, intent.action)
    intent_id = _intent_id(intent)
    material = repr(
        (
            intent_id,
            market.snapshot_id,
            market.decision_ts_ms,
            execution_side,
            requested,
            bool(strict_book),
        )
    )
    return ExecutionPlan(
        plan_id="paper-plan:" + sha256(material.encode("utf-8")).hexdigest(),
        intent_id=intent_id,
        strategy_id=str(intent.strategy_id),
        coin=market.coin,
        action=intent.action,
        position_side=intent.position_side,
        execution_side=execution_side,
        requested_notional_usdc=requested,
        decision_ts_ms=market.decision_ts_ms,
        snapshot_id=market.snapshot_id,
        strict_book=bool(strict_book),
    )


def execute_paper_intent(
    intent: PaperExecutionIntent,
    market: CausalMarketSnapshot,
    *,
    config: ExecModelConfig | None = None,
    strict_book: bool = True,
    min_fill_ratio: float = 0.0,
    max_book_age_ms: int = 5_000,
    is_maker: bool = False,
    latency_sec: float = 0.0,
    top_depth_usdc: float | None = None,
    queue_ahead_usdc: float = 0.0,
    queue_depletion_usdc: float | None = None,
    traded_through_usdc: float | None = None,
    adverse_selection_bps: float | None = None,
    liquidity_ledger: LiquidityConsumptionLedger | None = None,
) -> CanonicalExecutionResult:
    """Execute one intent with the unique fill model and produce mutations."""

    plan = build_execution_plan(intent, market, strict_book=strict_book)
    def run_execution(truth: ExecutionTruth | None) -> ExecResult:
        if market.execution_truth is not None and truth is None:
            return _consumed_book_result(
                requested_notional_usdc=plan.requested_notional_usdc,
                snapshot_id=market.execution_truth.snapshot_id,
            )
        return simulate_execution(
            side=plan.execution_side,
            notional_usdc=plan.requested_notional_usdc,
            mid_price=market.reference_mid,
            top_depth_usdc=top_depth_usdc,
            is_maker=is_maker,
            latency_sec=latency_sec,
            queue_ahead_usdc=queue_ahead_usdc,
            queue_depletion_usdc=queue_depletion_usdc,
            traded_through_usdc=traded_through_usdc,
            adverse_selection_bps=adverse_selection_bps,
            execution_truth=truth,
            decision_ts_ms=(
                market.decision_ts_ms
                if market.execution_truth is not None
                else None
            ),
            max_book_age_ms=max_book_age_ms,
            strict_book=strict_book,
            min_fill_ratio=min_fill_ratio,
            config=config,
        )

    reservation = None
    if (
        liquidity_ledger is not None
        and market.execution_truth is not None
        and not is_maker
    ):
        outcome = liquidity_ledger.execute_once(
            plan_id=plan.plan_id,
            truth=market.execution_truth,
            execution_side=plan.execution_side,
            execute=run_execution,
        )
        execution = outcome.result
        reservation = outcome.reservation
    else:
        execution = run_execution(market.execution_truth)
    signed_quantity = execution.filled_quantity
    if plan.action in {"REDUCE", "CLOSE"}:
        signed_quantity = -signed_quantity
    mutation = PositionMutation(
        action=plan.action,
        position_side=plan.position_side,
        quantity_delta=round(signed_quantity, 12),
        filled_notional_usdc=execution.filled_notional_usdc,
        fill_price=execution.fill_price,
        status="APPLY" if execution.filled_notional_usdc > 0 else "NO_MUTATION",
    )
    event_material = repr(
        (
            plan.plan_id,
            execution.execution_snapshot_id,
            execution.fill_price,
            execution.filled_notional_usdc,
            execution.reason,
        )
    )
    event_id = "paper-ledger:" + sha256(event_material.encode("utf-8")).hexdigest()
    ledger_event = LedgerEvent(
        event_id=event_id,
        event_type=plan.action,
        plan_id=plan.plan_id,
        strategy_id=plan.strategy_id,
        coin=plan.coin,
        position_side=plan.position_side,
        execution_side=plan.execution_side,
        requested_notional_usdc=execution.requested_notional_usdc,
        filled_notional_usdc=execution.filled_notional_usdc,
        missed_notional_usdc=execution.missed_notional_usdc,
        fill_price=execution.fill_price,
        fee_bps=execution.fee_bps,
        slippage_bps=execution.slippage_bps,
        latency_bps=execution.latency_bps,
        execution_snapshot_id=execution.execution_snapshot_id,
        cost_status=execution.cost_status,
        reason=execution.reason,
    )
    equity_event = EquityEvent(
        event_id="paper-equity:" + sha256(event_id.encode("utf-8")).hexdigest(),
        plan_id=plan.plan_id,
        filled_notional_usdc=execution.filled_notional_usdc,
        realized_pnl_delta_usdc=None,
        accounting_status="PENDING_POSITION_ACCOUNTING",
    )
    return CanonicalExecutionResult(
        plan=plan,
        execution=execution,
        position_mutation=mutation,
        ledger_event=ledger_event,
        equity_event=equity_event,
        liquidity_reservation=reservation,
    )


def execution_side_for(side: str, action: str) -> str:
    normalized_side = str(side or "").strip().upper()
    normalized_action = str(action or "").strip().upper()
    if normalized_action in {"OPEN", "ADD"}:
        if normalized_side == "LONG":
            return "BUY"
        if normalized_side == "SHORT":
            return "SELL"
    if normalized_action in {"REDUCE", "CLOSE"}:
        if normalized_side == "LONG":
            return "SELL"
        if normalized_side == "SHORT":
            return "BUY"
    raise ValueError(f"unsupported paper side/action pair: {side}/{action}")


def _intent_id(intent: PaperExecutionIntent) -> str:
    material = repr(
        (
            intent.strategy_id,
            str(intent.coin).upper(),
            intent.position_side,
            intent.action,
            float(intent.target_notional_usdc),
            int(intent.created_at_ms),
            tuple(intent.reasons),
        )
    )
    return "paper-intent:" + sha256(material.encode("utf-8")).hexdigest()


def _consumed_book_result(
    *,
    requested_notional_usdc: float,
    snapshot_id: str,
) -> ExecResult:
    requested = round(float(requested_notional_usdc), 8)
    return ExecResult(
        fill_price=None,
        slippage_bps=None,
        fee_bps=None,
        latency_bps=0.0,
        net_cost_bps=None,
        queue_ratio=None,
        is_maker=False,
        notional_usdc=0.0,
        requested_notional_usdc=requested,
        filled_notional_usdc=0.0,
        missed_notional_usdc=requested,
        fill_ratio=0.0,
        partial=False,
        missed=True,
        reason="LIQUIDITY_ALREADY_CONSUMED",
        cost_status="MEASURED",
        execution_snapshot_id=snapshot_id,
        filled_quantity=0.0,
    )


__all__ = [
    "CanonicalExecutionResult",
    "CausalMarketSnapshot",
    "EquityEvent",
    "ExecutionPlan",
    "LedgerEvent",
    "PaperExecutionIntent",
    "PositionMutation",
    "build_execution_plan",
    "execute_paper_intent",
    "execution_side_for",
]
