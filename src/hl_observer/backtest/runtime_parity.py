from __future__ import annotations

from dataclasses import dataclass

from hl_observer.config.settings import Settings
from hl_observer.copying import PaperSimulationDecision, run_paper_simulation_decision
from hl_observer.features import MarketFeatureVector
from hl_observer.hyperliquid.schemas import SignalCandidate
from hl_observer.paper.paper_executor import PaperExecutor
from hl_observer.storage.run_context import RunContext, RunContextScope, build_run_context_scope, may_merge_pnl


@dataclass(frozen=True, slots=True)
class RuntimeReplayParityResult:
    runtime_scope: RunContextScope
    replay_scope: RunContextScope
    runtime_decision: PaperSimulationDecision
    replay_decision: PaperSimulationDecision
    economics_match: bool
    risk_match: bool
    pnl_may_merge: bool
    warnings: tuple[str, ...]


def compare_runtime_replay_paper(
    *,
    signal: SignalCandidate,
    market: MarketFeatureVector | None,
    settings: Settings | None = None,
    notional_usdc: float = 100.0,
    runtime_run_id: str = "live-paper",
    replay_run_id: str = "replay-paper",
) -> RuntimeReplayParityResult:
    """Compare deterministic paper economics between live simulation and replay.

    The two contexts intentionally do not merge PnL. The comparison verifies
    that identical read-only inputs produce identical paper economics and risk
    decisions, while their run namespaces remain isolated.
    """

    settings = settings or Settings()
    runtime_scope = build_run_context_scope(RunContext.LIVE, run_id=runtime_run_id)
    replay_scope = build_run_context_scope(RunContext.REPLAY, run_id=replay_run_id)
    runtime_decision = run_paper_simulation_decision(
        signal=signal,
        market=market,
        settings=settings,
        executor=PaperExecutor(),
        run_id=runtime_scope.run_id,
        notional_usdc=notional_usdc,
    )
    replay_decision = run_paper_simulation_decision(
        signal=signal,
        market=market,
        settings=settings,
        executor=PaperExecutor(),
        run_id=replay_scope.run_id,
        notional_usdc=notional_usdc,
    )
    economics_match = _paper_economics_tuple(runtime_decision) == _paper_economics_tuple(replay_decision)
    risk_match = _risk_tuple(runtime_decision) == _risk_tuple(replay_decision)
    pnl_may_merge = may_merge_pnl(runtime_scope, replay_scope)
    warnings: list[str] = []
    if not economics_match:
        warnings.append("PAPER_ECONOMICS_DIVERGED")
    if not risk_match:
        warnings.append("RISK_DECISION_DIVERGED")
    if pnl_may_merge:
        warnings.append("PNL_CONTEXT_UNEXPECTEDLY_MERGEABLE")
    return RuntimeReplayParityResult(
        runtime_scope=runtime_scope,
        replay_scope=replay_scope,
        runtime_decision=runtime_decision,
        replay_decision=replay_decision,
        economics_match=economics_match,
        risk_match=risk_match,
        pnl_may_merge=pnl_may_merge,
        warnings=tuple(warnings),
    )


def _paper_economics_tuple(decision: PaperSimulationDecision) -> tuple:
    order = decision.paper_order
    return (
        order.coin,
        order.side,
        round(order.notional_usdc, 12),
        round(order.requested_price, 12),
        round(order.simulated_fill_price, 12),
        round(order.fee_bps, 12),
        round(order.slippage_bps, 12),
        order.rejected_reason,
    )


def _risk_tuple(decision: PaperSimulationDecision) -> tuple:
    risk = decision.risk_decision
    return (
        risk.allowed,
        getattr(risk.decision, "value", str(risk.decision)),
        tuple(risk.reasons),
        tuple(sorted(risk.gates.items())),
    )
