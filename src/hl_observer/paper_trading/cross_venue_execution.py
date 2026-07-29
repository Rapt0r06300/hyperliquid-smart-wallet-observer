"""Non-atomic cross-venue execution for local paper research.

The two legs of an arbitrage never share an imaginary simultaneous fill.  The
first leg consumes its observed book, the second leg consumes a distinct book
observed after measured latency, and any unmatched first-leg quantity is
unwound against a third causal book.  All authoritative mutations are written
to :class:`PaperLedger`; P95/P99 scenarios use isolated ledgers.

This module is paper-only.  It has no network client, signer, key handling, or
venue order surface.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from hl_observer.paper_trading.canonical_execution import (
    CanonicalExecutionResult,
    CausalMarketSnapshot,
    PaperExecutionIntent,
    execute_paper_intent,
)
from hl_observer.paper_trading.exec_model import ExecModelConfig
from hl_observer.paper_trading.liquidity_consumption import LiquidityConsumptionLedger
from hl_observer.simulation.paper_ledger import PaperLedger


class CrossVenueExecutionState(str, Enum):
    DETECTED = "DETECTED"
    LEG1_FILLED = "LEG1_FILLED"
    LEG1_PARTIAL = "LEG1_PARTIAL"
    LEG2_FILLED = "LEG2_FILLED"
    LEG2_PARTIAL = "LEG2_PARTIAL"
    RESIDUAL_UNWIND_FILLED = "RESIDUAL_UNWIND_FILLED"
    RESIDUAL_UNWIND_PARTIAL = "RESIDUAL_UNWIND_PARTIAL"
    MATCHED = "MATCHED"
    EXITING = "EXITING"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class StateTransition:
    state: CrossVenueExecutionState
    timestamp_ms: int
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "timestamp_ms": self.timestamp_ms,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class MeasuredLatencyDistribution:
    """Observed end-to-end leg latency, never a configured ``+1 bp`` proxy."""

    samples_ms: tuple[float, ...]
    source: str

    def __post_init__(self) -> None:
        samples = tuple(float(value) for value in self.samples_ms)
        if len(samples) < 3:
            raise ValueError("at least three measured latency samples are required")
        if any(not math.isfinite(value) or value < 0 for value in samples):
            raise ValueError("latency samples must be finite and non-negative")
        source = str(self.source or "").strip()
        if not source:
            raise ValueError("measured latency source is required")
        object.__setattr__(self, "samples_ms", tuple(sorted(samples)))
        object.__setattr__(self, "source", source)

    def percentile_ms(self, percentile: float) -> float:
        pct = float(percentile)
        if not 0 <= pct <= 100:
            raise ValueError("percentile must be between 0 and 100")
        if len(self.samples_ms) == 1:
            return self.samples_ms[0]
        position = (len(self.samples_ms) - 1) * pct / 100.0
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return self.samples_ms[lower]
        weight = position - lower
        return self.samples_ms[lower] * (1.0 - weight) + self.samples_ms[upper] * weight

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "sample_count": len(self.samples_ms),
            "p50_ms": round(self.percentile_ms(50), 6),
            "p95_ms": round(self.percentile_ms(95), 6),
            "p99_ms": round(self.percentile_ms(99), 6),
            "min_ms": round(self.samples_ms[0], 6),
            "max_ms": round(self.samples_ms[-1], 6),
        }


@dataclass(frozen=True, slots=True)
class CrossVenueLeg:
    venue: str
    coin: str
    action: str
    target_notional_usdc: float

    def __post_init__(self) -> None:
        venue = str(self.venue or "").strip().upper()
        coin = str(self.coin or "").strip().upper()
        action = str(self.action or "").strip().upper()
        target = float(self.target_notional_usdc)
        if not venue or not coin:
            raise ValueError("venue and coin are required")
        if action not in {"BUY", "SELL"}:
            raise ValueError("cross-venue action must be BUY or SELL")
        if not math.isfinite(target) or target <= 0:
            raise ValueError("target_notional_usdc must be finite and positive")
        object.__setattr__(self, "venue", venue)
        object.__setattr__(self, "coin", coin)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "target_notional_usdc", target)

    @property
    def position_side(self) -> str:
        return "LONG" if self.action == "BUY" else "SHORT"

    @property
    def ledger_coin(self) -> str:
        return f"{self.coin}@{self.venue}"


@dataclass(frozen=True, slots=True)
class CrossVenueExecutionRequest:
    request_id: str
    detected_ts_ms: int
    leg1: CrossVenueLeg
    leg2: CrossVenueLeg
    leverage: float = 1.0

    def __post_init__(self) -> None:
        request_id = str(self.request_id or "").strip()
        leverage = float(self.leverage)
        if not request_id:
            raise ValueError("request_id is required")
        if int(self.detected_ts_ms) <= 0:
            raise ValueError("detected_ts_ms must be positive")
        if self.leg1.coin != self.leg2.coin:
            raise ValueError("cross-venue legs must use the same coin")
        if self.leg1.venue == self.leg2.venue:
            raise ValueError("cross-venue legs must use distinct venues")
        if self.leg1.action == self.leg2.action:
            raise ValueError("cross-venue legs must be opposite")
        if not math.isfinite(leverage) or leverage < 1:
            raise ValueError("leverage must be finite and >= 1")
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "detected_ts_ms", int(self.detected_ts_ms))
        object.__setattr__(self, "leverage", leverage)


@dataclass(frozen=True, slots=True)
class CrossVenueScenarioSnapshots:
    label: str
    latency_ms: float
    leg1_entry: CausalMarketSnapshot
    leg2_delayed: CausalMarketSnapshot
    leg1_unwind_delayed: CausalMarketSnapshot

    def __post_init__(self) -> None:
        label = str(self.label or "").strip().upper()
        latency = float(self.latency_ms)
        if not label:
            raise ValueError("scenario label is required")
        if not math.isfinite(latency) or latency < 0:
            raise ValueError("scenario latency must be finite and non-negative")
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "latency_ms", latency)


@dataclass(frozen=True, slots=True)
class CrossVenueScenarioResult:
    label: str
    latency_ms: float
    transitions: tuple[StateTransition, ...]
    leg1_execution: dict[str, object]
    leg2_execution: dict[str, object] | None
    unwind_execution: dict[str, object] | None
    matched_quantity: float
    matched_notional_usdc: float
    paired_entry_edge_usdc: float
    initial_residual_notional_usdc: float
    remaining_residual_notional_usdc: float
    residual_realized_pnl_usdc: float
    equity_usdc: float
    realized_pnl_usdc: float
    fees_paid_usdc: float
    open_position_ids: tuple[str, ...]
    strict_result: bool
    paper_only: bool = True
    real_execution: bool = False

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["transitions"] = [transition.to_dict() for transition in self.transitions]
        payload["open_position_ids"] = list(self.open_position_ids)
        return payload


@dataclass(frozen=True, slots=True)
class CrossVenueExecutionReport:
    request_id: str
    leg_order: tuple[str, str]
    latency_distribution: dict[str, object]
    base: CrossVenueScenarioResult
    stress_p95: CrossVenueScenarioResult
    stress_p99: CrossVenueScenarioResult
    paper_only: bool = True
    real_execution: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "leg_order": list(self.leg_order),
            "latency_distribution": dict(self.latency_distribution),
            "base": self.base.to_dict(),
            "stress_p95": self.stress_p95.to_dict(),
            "stress_p99": self.stress_p99.to_dict(),
            "paper_only": True,
            "real_execution": False,
        }


def execute_non_atomic_cross_venue(
    request: CrossVenueExecutionRequest,
    *,
    latency_distribution: MeasuredLatencyDistribution,
    base: CrossVenueScenarioSnapshots,
    stress_p95: CrossVenueScenarioSnapshots,
    stress_p99: CrossVenueScenarioSnapshots,
    ledger: PaperLedger,
    config: ExecModelConfig | None = None,
    liquidity_ledger: LiquidityConsumptionLedger | None = None,
    max_book_age_ms: int = 5_000,
    min_fill_ratio: float = 0.0,
) -> CrossVenueExecutionReport:
    """Execute P50 and measure isolated P95/P99 non-atomic outcomes."""

    _validate_scenario(
        request,
        base,
        minimum_latency_ms=latency_distribution.percentile_ms(50),
    )
    _validate_scenario(
        request,
        stress_p95,
        minimum_latency_ms=latency_distribution.percentile_ms(95),
    )
    _validate_scenario(
        request,
        stress_p99,
        minimum_latency_ms=latency_distribution.percentile_ms(99),
    )
    cfg = config or ExecModelConfig()
    base_result = _run_scenario(
        request,
        base,
        ledger=ledger,
        config=cfg,
        liquidity_ledger=liquidity_ledger or LiquidityConsumptionLedger(),
        max_book_age_ms=max_book_age_ms,
        min_fill_ratio=min_fill_ratio,
    )
    p95_ledger = PaperLedger(
        starting_balance_usdc=ledger.starting_balance_usdc,
        session_id=f"{ledger.session_id}:{request.request_id}:P95",
    )
    p99_ledger = PaperLedger(
        starting_balance_usdc=ledger.starting_balance_usdc,
        session_id=f"{ledger.session_id}:{request.request_id}:P99",
    )
    p95_result = _run_scenario(
        request,
        stress_p95,
        ledger=p95_ledger,
        config=cfg,
        liquidity_ledger=LiquidityConsumptionLedger(),
        max_book_age_ms=max_book_age_ms,
        min_fill_ratio=min_fill_ratio,
    )
    p99_result = _run_scenario(
        request,
        stress_p99,
        ledger=p99_ledger,
        config=cfg,
        liquidity_ledger=LiquidityConsumptionLedger(),
        max_book_age_ms=max_book_age_ms,
        min_fill_ratio=min_fill_ratio,
    )
    return CrossVenueExecutionReport(
        request_id=request.request_id,
        leg_order=(request.leg1.venue, request.leg2.venue),
        latency_distribution=latency_distribution.to_dict(),
        base=base_result,
        stress_p95=p95_result,
        stress_p99=p99_result,
    )


def _run_scenario(
    request: CrossVenueExecutionRequest,
    scenario: CrossVenueScenarioSnapshots,
    *,
    ledger: PaperLedger,
    config: ExecModelConfig,
    liquidity_ledger: LiquidityConsumptionLedger,
    max_book_age_ms: int,
    min_fill_ratio: float,
) -> CrossVenueScenarioResult:
    transitions: list[StateTransition] = [
        StateTransition(
            CrossVenueExecutionState.DETECTED,
            request.detected_ts_ms,
            f"{request.leg1.venue}->{request.leg2.venue}",
        )
    ]
    leg1_result = _execute_leg(
        request,
        request.leg1,
        scenario.leg1_entry,
        notional_usdc=request.leg1.target_notional_usdc,
        strategy_suffix=f"{scenario.label}:LEG1",
        config=config,
        liquidity_ledger=liquidity_ledger,
        max_book_age_ms=max_book_age_ms,
        min_fill_ratio=min_fill_ratio,
    )
    leg1_filled = leg1_result.execution.filled_notional_usdc
    if not leg1_result.accepted:
        transitions.append(
            StateTransition(
                CrossVenueExecutionState.REJECTED,
                scenario.leg1_entry.decision_ts_ms,
                f"LEG1:{leg1_result.execution.reason}",
            )
        )
        ledger.no_trade(
            coin=request.leg1.coin,
            reason="CROSS_VENUE_LEG1_UNFILLED",
            timestamp_ms=scenario.leg1_entry.decision_ts_ms,
            refs=_execution_refs(request, scenario, leg1_result),
        )
        return _scenario_result(
            scenario,
            transitions,
            leg1_result,
            None,
            None,
            ledger,
            matched=0.0,
            matched_quantity=0.0,
            paired_entry_edge=0.0,
            initial_residual=0.0,
            remaining_residual=0.0,
            residual_realized=0.0,
            strict_result=False,
        )

    transitions.append(
        StateTransition(
            (
                CrossVenueExecutionState.LEG1_PARTIAL
                if leg1_result.execution.partial
                else CrossVenueExecutionState.LEG1_FILLED
            ),
            scenario.leg1_entry.decision_ts_ms,
            f"{leg1_filled:.8f} USDC",
        )
    )
    leg1_position_id = _position_id(request, scenario.label, request.leg1)
    ledger.open_position(
        coin=request.leg1.ledger_coin,
        side=request.leg1.position_side,
        notional_usdc=leg1_filled,
        quantity=leg1_result.execution.filled_quantity,
        fill_price=float(leg1_result.execution.fill_price),
        timestamp_ms=scenario.leg1_entry.decision_ts_ms,
        fee_bps=0.0,
        leverage_effective=request.leverage,
        position_id=leg1_position_id,
        refs=_execution_refs(request, scenario, leg1_result),
    )

    leg1_quantity = leg1_result.execution.filled_quantity
    leg2_target = min(
        request.leg2.target_notional_usdc,
        leg1_quantity * scenario.leg2_delayed.reference_mid,
    )
    leg2_result = _execute_leg(
        request,
        request.leg2,
        scenario.leg2_delayed,
        notional_usdc=leg2_target,
        strategy_suffix=f"{scenario.label}:LEG2",
        config=config,
        liquidity_ledger=liquidity_ledger,
        max_book_age_ms=max_book_age_ms,
        min_fill_ratio=min_fill_ratio,
    )
    leg2_filled = (
        leg2_result.execution.filled_notional_usdc
        if leg2_result.accepted
        else 0.0
    )
    transitions.append(
        StateTransition(
            (
                CrossVenueExecutionState.LEG2_PARTIAL
                if leg2_result.execution.partial or not leg2_result.accepted
                else CrossVenueExecutionState.LEG2_FILLED
            ),
            scenario.leg2_delayed.decision_ts_ms,
            (
                f"{leg2_filled:.8f} USDC"
                if leg2_result.accepted
                else f"0 USDC:{leg2_result.execution.reason}"
            ),
        )
    )
    if leg2_result.accepted:
        ledger.open_position(
            coin=request.leg2.ledger_coin,
            side=request.leg2.position_side,
            notional_usdc=leg2_filled,
            quantity=leg2_result.execution.filled_quantity,
            fill_price=float(leg2_result.execution.fill_price),
            timestamp_ms=scenario.leg2_delayed.decision_ts_ms,
            fee_bps=0.0,
            leverage_effective=request.leverage,
            position_id=_position_id(request, scenario.label, request.leg2),
            refs=_execution_refs(request, scenario, leg2_result),
        )

    matched_quantity = min(
        leg1_quantity,
        (
            max(0.0, leg2_result.execution.filled_quantity)
            if leg2_result.accepted
            else 0.0
        ),
    )
    leg1_entry_price = float(leg1_result.execution.fill_price)
    matched = matched_quantity * leg1_entry_price
    paired_entry_edge = _paired_entry_edge(
        request,
        matched_quantity=matched_quantity,
        leg1_fill_price=leg1_entry_price,
        leg2_fill_price=(
            float(leg2_result.execution.fill_price)
            if leg2_result.execution.fill_price is not None
            else None
        ),
    )
    residual_quantity = max(0.0, leg1_quantity - matched_quantity)
    initial_residual = residual_quantity * leg1_entry_price
    remaining_residual = initial_residual
    residual_realized = 0.0
    unwind_result: CanonicalExecutionResult | None = None
    if initial_residual > 1e-8:
        transitions.append(
            StateTransition(
                CrossVenueExecutionState.EXITING,
                scenario.leg1_unwind_delayed.decision_ts_ms,
                f"unwind residual {initial_residual:.8f} USDC",
            )
        )
        unwind_target = residual_quantity * scenario.leg1_unwind_delayed.reference_mid
        unwind_result = _execute_close(
            request,
            request.leg1,
            scenario.leg1_unwind_delayed,
            notional_usdc=unwind_target,
            strategy_suffix=f"{scenario.label}:RESIDUAL_UNWIND",
            config=config,
            liquidity_ledger=liquidity_ledger,
            max_book_age_ms=max_book_age_ms,
            min_fill_ratio=0.0,
        )
        unwind_quantity = min(
            residual_quantity,
            max(0.0, unwind_result.execution.filled_quantity),
        )
        if unwind_result.accepted and unwind_quantity > 0:
            event = ledger.reduce_or_close(
                coin=request.leg1.ledger_coin,
                side=request.leg1.position_side,
                quantity=unwind_quantity,
                fill_price=float(unwind_result.execution.fill_price),
                timestamp_ms=scenario.leg1_unwind_delayed.decision_ts_ms,
                fee_bps=0.0,
                reason="cross_venue_residual_unwind",
                position_id=leg1_position_id,
                refs=_execution_refs(request, scenario, unwind_result),
            )
            residual_realized = float(event.realized_pnl_usdc)
            remaining_residual = max(
                0.0,
                (residual_quantity - unwind_quantity) * leg1_entry_price,
            )
            transitions.append(
                StateTransition(
                    (
                        CrossVenueExecutionState.RESIDUAL_UNWIND_FILLED
                        if remaining_residual <= 1e-6
                        else CrossVenueExecutionState.RESIDUAL_UNWIND_PARTIAL
                    ),
                    scenario.leg1_unwind_delayed.decision_ts_ms,
                    (
                        f"realized={residual_realized:.10f}; "
                        f"remaining={remaining_residual:.10f}"
                    ),
                )
            )
        else:
            transitions.append(
                StateTransition(
                    CrossVenueExecutionState.RESIDUAL_UNWIND_PARTIAL,
                    scenario.leg1_unwind_delayed.decision_ts_ms,
                    f"unwind failed:{unwind_result.execution.reason}",
                )
            )

    strict_result = remaining_residual <= 1e-6
    if matched > 1e-8 and strict_result:
        transitions.append(
            StateTransition(
                CrossVenueExecutionState.MATCHED,
                scenario.leg1_unwind_delayed.decision_ts_ms,
                f"matched={matched:.8f} USDC",
            )
        )
    elif matched <= 1e-8 and strict_result:
        transitions.append(
            StateTransition(
                CrossVenueExecutionState.CLOSED,
                scenario.leg1_unwind_delayed.decision_ts_ms,
                "leg1 fully unwound; no pair remains",
            )
        )
    else:
        ledger.no_trade(
            coin=request.leg1.coin,
            reason="CROSS_VENUE_RESIDUAL_LEG_RISK",
            timestamp_ms=scenario.leg1_unwind_delayed.decision_ts_ms,
            refs={
                "request_id": request.request_id,
                "scenario": scenario.label,
                "remaining_residual_notional_usdc": remaining_residual,
            },
        )
    return _scenario_result(
        scenario,
        transitions,
        leg1_result,
        leg2_result,
        unwind_result,
        ledger,
        matched=matched,
        matched_quantity=matched_quantity,
        paired_entry_edge=paired_entry_edge,
        initial_residual=initial_residual,
        remaining_residual=remaining_residual,
        residual_realized=residual_realized,
        strict_result=strict_result,
    )


def _execute_leg(
    request: CrossVenueExecutionRequest,
    leg: CrossVenueLeg,
    snapshot: CausalMarketSnapshot,
    *,
    notional_usdc: float,
    strategy_suffix: str,
    config: ExecModelConfig,
    liquidity_ledger: LiquidityConsumptionLedger,
    max_book_age_ms: int,
    min_fill_ratio: float,
) -> CanonicalExecutionResult:
    return execute_paper_intent(
        PaperExecutionIntent(
            strategy_id=f"cross_venue:{request.request_id}:{strategy_suffix}",
            coin=leg.coin,
            position_side=leg.position_side,
            action="OPEN",
            target_notional_usdc=notional_usdc,
            created_at_ms=request.detected_ts_ms,
            reasons=("NON_ATOMIC_CROSS_VENUE",),
        ),
        snapshot,
        config=config,
        strict_book=True,
        min_fill_ratio=min_fill_ratio,
        max_book_age_ms=max_book_age_ms,
        is_maker=False,
        latency_sec=0.0,
        liquidity_ledger=liquidity_ledger,
    )


def _execute_close(
    request: CrossVenueExecutionRequest,
    leg: CrossVenueLeg,
    snapshot: CausalMarketSnapshot,
    *,
    notional_usdc: float,
    strategy_suffix: str,
    config: ExecModelConfig,
    liquidity_ledger: LiquidityConsumptionLedger,
    max_book_age_ms: int,
    min_fill_ratio: float,
) -> CanonicalExecutionResult:
    return execute_paper_intent(
        PaperExecutionIntent(
            strategy_id=f"cross_venue:{request.request_id}:{strategy_suffix}",
            coin=leg.coin,
            position_side=leg.position_side,
            action="CLOSE",
            target_notional_usdc=max(notional_usdc, 1e-8),
            created_at_ms=request.detected_ts_ms,
            reasons=("RESIDUAL_LEG_UNWIND",),
        ),
        snapshot,
        config=config,
        strict_book=True,
        min_fill_ratio=min_fill_ratio,
        max_book_age_ms=max_book_age_ms,
        is_maker=False,
        latency_sec=0.0,
        liquidity_ledger=liquidity_ledger,
    )


def _validate_scenario(
    request: CrossVenueExecutionRequest,
    scenario: CrossVenueScenarioSnapshots,
    *,
    minimum_latency_ms: float,
) -> None:
    snapshots = (
        scenario.leg1_entry,
        scenario.leg2_delayed,
        scenario.leg1_unwind_delayed,
    )
    if any(snapshot.coin != request.leg1.coin for snapshot in snapshots):
        raise ValueError(f"{scenario.label}: snapshot coin mismatch")
    if scenario.latency_ms + 1e-9 < minimum_latency_ms:
        raise ValueError(
            f"{scenario.label}: latency is below measured percentile "
            f"({scenario.latency_ms} < {minimum_latency_ms})"
        )
    if scenario.latency_ms > 0:
        if scenario.leg1_entry.snapshot_id == scenario.leg2_delayed.snapshot_id:
            raise ValueError(f"{scenario.label}: leg2 reused the leg1 snapshot")
        if scenario.leg1_entry.snapshot_id == scenario.leg1_unwind_delayed.snapshot_id:
            raise ValueError(f"{scenario.label}: unwind reused the leg1 snapshot")
    required_delayed_ts = scenario.leg1_entry.decision_ts_ms + int(
        math.ceil(scenario.latency_ms)
    )
    if scenario.leg2_delayed.decision_ts_ms < required_delayed_ts:
        raise ValueError(f"{scenario.label}: leg2 snapshot predates measured latency")
    if scenario.leg1_unwind_delayed.decision_ts_ms < required_delayed_ts:
        raise ValueError(f"{scenario.label}: unwind snapshot predates measured latency")


def _scenario_result(
    scenario: CrossVenueScenarioSnapshots,
    transitions: list[StateTransition],
    leg1: CanonicalExecutionResult,
    leg2: CanonicalExecutionResult | None,
    unwind: CanonicalExecutionResult | None,
    ledger: PaperLedger,
    *,
    matched: float,
    matched_quantity: float,
    paired_entry_edge: float,
    initial_residual: float,
    remaining_residual: float,
    residual_realized: float,
    strict_result: bool,
) -> CrossVenueScenarioResult:
    snapshot = ledger.snapshot()
    return CrossVenueScenarioResult(
        label=scenario.label,
        latency_ms=scenario.latency_ms,
        transitions=tuple(transitions),
        leg1_execution=leg1.as_dict(),
        leg2_execution=leg2.as_dict() if leg2 is not None else None,
        unwind_execution=unwind.as_dict() if unwind is not None else None,
        matched_quantity=round(matched_quantity, 12),
        matched_notional_usdc=round(matched, 10),
        paired_entry_edge_usdc=round(paired_entry_edge, 10),
        initial_residual_notional_usdc=round(initial_residual, 10),
        remaining_residual_notional_usdc=round(remaining_residual, 10),
        residual_realized_pnl_usdc=round(residual_realized, 10),
        equity_usdc=float(snapshot["equity_usdc"]),
        realized_pnl_usdc=float(snapshot["realized_pnl_usdc"]),
        fees_paid_usdc=float(snapshot["fees_paid_usdc"]),
        open_position_ids=tuple(sorted(ledger.positions)),
        strict_result=bool(strict_result and snapshot["strict_pnl_allowed"]),
    )


def _execution_refs(
    request: CrossVenueExecutionRequest,
    scenario: CrossVenueScenarioSnapshots,
    result: CanonicalExecutionResult,
) -> dict[str, Any]:
    return {
        "request_id": request.request_id,
        "scenario": scenario.label,
        "latency_ms": scenario.latency_ms,
        "execution_plan_id": result.plan.plan_id,
        "execution_event_id": result.ledger_event.event_id,
        "execution_snapshot_id": result.execution.execution_snapshot_id,
        "cost_status": result.execution.cost_status,
        "paper_only": True,
        "real_execution": False,
    }


def _paired_entry_edge(
    request: CrossVenueExecutionRequest,
    *,
    matched_quantity: float,
    leg1_fill_price: float,
    leg2_fill_price: float | None,
) -> float:
    if matched_quantity <= 0 or leg2_fill_price is None:
        return 0.0
    if request.leg1.action == "BUY":
        return (leg2_fill_price - leg1_fill_price) * matched_quantity
    return (leg1_fill_price - leg2_fill_price) * matched_quantity


def _position_id(
    request: CrossVenueExecutionRequest,
    scenario_label: str,
    leg: CrossVenueLeg,
) -> str:
    return (
        f"cross-venue:{request.request_id}:{scenario_label}:"
        f"{leg.venue}:{leg.action}"
    )


__all__ = [
    "CrossVenueExecutionReport",
    "CrossVenueExecutionRequest",
    "CrossVenueExecutionState",
    "CrossVenueLeg",
    "CrossVenueScenarioResult",
    "CrossVenueScenarioSnapshots",
    "MeasuredLatencyDistribution",
    "StateTransition",
    "execute_non_atomic_cross_venue",
]
