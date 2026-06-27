from __future__ import annotations

from dataclasses import dataclass

from hl_observer.config.settings import Settings
from hl_observer.features import MarketFeatureVector
from hl_observer.hyperliquid.schemas import PaperOrder, RiskDecision, SignalCandidate
from hl_observer.ledger import EvidenceChainEntry, build_evidence_entry
from hl_observer.paper.paper_executor import PaperExecutor
from hl_observer.risk.gates import RiskContext
from hl_observer.risk.risk_engine import RiskEngine


@dataclass(frozen=True, slots=True)
class PaperSimulationDecision:
    signal: SignalCandidate
    market: MarketFeatureVector | None
    risk_context: RiskContext
    risk_decision: RiskDecision
    paper_order: PaperOrder
    evidence: EvidenceChainEntry

    @property
    def accepted(self) -> bool:
        return self.risk_decision.allowed and self.paper_order.notional_usdc > 0

    @property
    def reasons(self) -> tuple[str, ...]:
        reasons = tuple(self.risk_decision.reasons)
        if self.market and self.market.quality_mode == "NO_TRADE":
            reasons += self.market.quality_reasons
        return tuple(dict.fromkeys(reasons))


def build_risk_context_from_signal(
    signal: SignalCandidate,
    market: MarketFeatureVector | None,
) -> RiskContext:
    spread_bps = _market_or_signal_spread(signal, market)
    orderbook_depth = _orderbook_depth(signal, market)
    market_edge_addon = market.min_edge_bps_addon if market else 50.0
    edge_remaining_bps = signal.edge_remaining_bps - market_edge_addon
    data_gap = market is None or market.quality_mode == "NO_TRADE" or "MARKET_FEATURES_MISSING" in (market.quality_reasons if market else ())
    return RiskContext(
        spread_bps=spread_bps,
        estimated_slippage_bps=signal.estimated_slippage_bps,
        orderbook_depth_usdc=orderbook_depth,
        wallet_score=signal.wallet_score,
        signal_score=signal.signal_score,
        edge_remaining_bps=edge_remaining_bps,
        signal_age_ms=signal.signal_age_ms,
        data_gap=data_gap,
    )


def run_paper_simulation_decision(
    *,
    signal: SignalCandidate,
    market: MarketFeatureVector | None,
    settings: Settings | None = None,
    executor: PaperExecutor | None = None,
    run_id: str,
    notional_usdc: float,
    source_refs: tuple[str, ...] = ("allMids", "l2Book"),
) -> PaperSimulationDecision:
    settings = settings or Settings()
    executor = executor or PaperExecutor()
    risk_context = build_risk_context_from_signal(signal, market)
    risk_decision = RiskEngine(settings).evaluate(risk_context)
    effective_signal = signal.model_copy(
        update={
            "edge_remaining_bps": risk_context.edge_remaining_bps,
            "estimated_spread_bps": risk_context.spread_bps,
            "orderbook_depth_usdc": risk_context.orderbook_depth_usdc,
        }
    )
    paper_order = executor.submit(effective_signal, risk_decision, notional_usdc=notional_usdc)
    evidence = build_evidence_entry(
        run_id=run_id,
        signal=effective_signal,
        market=market,
        risk_decision=risk_decision,
        paper_order=paper_order,
        source_refs=source_refs,
    )
    return PaperSimulationDecision(
        signal=effective_signal,
        market=market,
        risk_context=risk_context,
        risk_decision=risk_decision,
        paper_order=paper_order,
        evidence=evidence,
    )


def _market_or_signal_spread(signal: SignalCandidate, market: MarketFeatureVector | None) -> float:
    if market and market.spread_bps is not None:
        return market.spread_bps
    return signal.estimated_spread_bps


def _orderbook_depth(signal: SignalCandidate, market: MarketFeatureVector | None) -> float:
    if market:
        return market.bid_depth_usdc + market.ask_depth_usdc
    return signal.orderbook_depth_usdc
