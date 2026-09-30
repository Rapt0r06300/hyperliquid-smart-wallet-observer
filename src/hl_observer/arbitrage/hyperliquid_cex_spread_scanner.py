from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from hl_observer.arbitrage.funding_adjusted_edge import funding_adjusted_edge_bps
from hl_observer.arbitrage.opportunity_model import (
    PaperArbitrageLeg,
    PaperArbitrageOpportunity,
    build_paper_arbitrage_opportunity,
)
from hl_observer.arbitrage.orderbook_snapshot import OrderBookSnapshot
from hl_observer.arbitrage.spread_formula import CrossExchangeSpread, compute_cross_exchange_spread
from hl_observer.risk.risk_engine_v3 import V19RiskConfig, V19RiskDecision, decision_to_dict, evaluate_v19_risk_gates


@dataclass(frozen=True, slots=True)
class CrossExchangeOpportunity:
    spread: CrossExchangeSpread
    paper_opportunity: PaperArbitrageOpportunity
    risk_decision: V19RiskDecision
    funding_adjusted_edge_bps: float
    decision: str
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    paper_only: bool = True
    real_execution: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "spread": asdict(self.spread),
            "paper_opportunity": asdict(self.paper_opportunity),
            "risk_decision": decision_to_dict(self.risk_decision),
            "funding_adjusted_edge_bps": self.funding_adjusted_edge_bps,
            "reason_codes": list(self.reason_codes),
            "paper_only": True,
            "real_execution": False,
        }


def scan_hyperliquid_cex_spread(
    *,
    hyperliquid_book: OrderBookSnapshot,
    cex_book: OrderBookSnapshot,
    fee_bps: float = 6.0,
    slippage_bps: float = 4.0,
    latency_penalty_bps: float = 2.0,
    funding_rate: float = 0.0,
    risk_config: V19RiskConfig | None = None,
) -> CrossExchangeOpportunity:
    """Rank a Hyperliquid-vs-CEX price difference as paper-only opportunity."""

    candidates = [
        compute_cross_exchange_spread(
            long_book=hyperliquid_book,
            short_book=cex_book,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            latency_penalty_bps=latency_penalty_bps,
        ),
        compute_cross_exchange_spread(
            long_book=cex_book,
            short_book=hyperliquid_book,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            latency_penalty_bps=latency_penalty_bps,
        ),
    ]
    spread = sorted(candidates, key=lambda item: item.net_edge_bps, reverse=True)[0]
    funding = funding_adjusted_edge_bps(
        gross_edge_bps=spread.net_edge_bps,
        funding_rate=funding_rate,
        side="LONG",
    )
    paper = build_paper_arbitrage_opportunity(
        long_leg=PaperArbitrageLeg(
            source=spread.long_source,
            coin=spread.coin,
            side="LONG",
            price=spread.long_price,
            fee_bps=fee_bps / 2.0,
            slippage_bps=slippage_bps / 2.0,
            liquidity_score=min(hyperliquid_book.depth_score, cex_book.depth_score),
        ),
        short_leg=PaperArbitrageLeg(
            source=spread.short_source,
            coin=spread.coin,
            side="SHORT",
            price=spread.short_price,
            fee_bps=fee_bps / 2.0,
            slippage_bps=slippage_bps / 2.0,
            liquidity_score=min(hyperliquid_book.depth_score, cex_book.depth_score),
        ),
    )
    reasons = list(spread.reason_codes) + list(paper.reason_codes)
    if funding.adjusted_edge_bps <= 0:
        reasons.append("FUNDING_ADJUSTED_EDGE_TOO_LOW")
    risk = evaluate_v19_risk_gates(
        net_pnl_usdc=0.0,
        total_decisions=1,
        accepted=0 if reasons else 1,
        negative_events=0,
        positive_events=1 if not reasons else 0,
        fee_drag_ratio=0.0,
        stale_reason_count=0,
        edge_negative_count=0 if not reasons else 1,
        edge_sentinel_count=0,
        orphan_close_count=0,
        profit_factor_net=1.1,
        config=risk_config,
    )
    reasons.extend(risk.blocking_codes)
    unique = tuple(dict.fromkeys(reasons))
    accepted = spread.accepted and paper.accepted and not unique and risk.allow_new_entries
    return CrossExchangeOpportunity(
        spread=spread,
        paper_opportunity=paper,
        risk_decision=risk,
        funding_adjusted_edge_bps=round(funding.adjusted_edge_bps, 8),
        decision="ACCEPT_PAPER_ARBITRAGE" if accepted else "NO_TRADE",
        reason_codes=unique,
    )


__all__ = ["CrossExchangeOpportunity", "scan_hyperliquid_cex_spread"]
