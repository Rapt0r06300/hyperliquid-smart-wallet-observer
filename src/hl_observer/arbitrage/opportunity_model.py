"""Paper-only arbitrage opportunity model.

No venue action is possible here: this is only a net-edge calculator for the
dashboard/backtests and for future paper strategies.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.edge.margin_of_safety import MarginOfSafetyConfig, evaluate_margin_of_safety


@dataclass(frozen=True, slots=True)
class PaperArbitrageLeg:
    source: str
    coin: str
    side: str
    price: float
    fee_bps: float = 0.0
    slippage_bps: float = 0.0
    liquidity_score: float = 1.0


@dataclass(frozen=True, slots=True)
class PaperArbitrageOpportunity:
    accepted: bool
    coin: str
    long_source: str
    short_source: str
    gross_spread_bps: float
    total_cost_bps: float
    net_edge_bps: float
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    paper_only: bool = True
    external_action: bool = False


def build_paper_arbitrage_opportunity(
    *,
    long_leg: PaperArbitrageLeg,
    short_leg: PaperArbitrageLeg,
    min_liquidity_score: float = 0.35,
    margin_config: MarginOfSafetyConfig | None = None,
) -> PaperArbitrageOpportunity:
    reasons: list[str] = []
    if long_leg.coin.upper() != short_leg.coin.upper():
        reasons.append("ARBITRAGE_COIN_MISMATCH")
    if long_leg.source == short_leg.source:
        reasons.append("ARBITRAGE_REQUIRES_TWO_SOURCES")
    if long_leg.price <= 0 or short_leg.price <= 0:
        reasons.append("ARBITRAGE_PRICE_INVALID")
    if min(long_leg.liquidity_score, short_leg.liquidity_score) < min_liquidity_score:
        reasons.append("ARBITRAGE_LIQUIDITY_TOO_LOW")
    if reasons:
        return PaperArbitrageOpportunity(
            accepted=False,
            coin=long_leg.coin.upper(),
            long_source=long_leg.source,
            short_source=short_leg.source,
            gross_spread_bps=0.0,
            total_cost_bps=0.0,
            net_edge_bps=0.0,
            reason_codes=tuple(dict.fromkeys(reasons)),
        )
    gross = (short_leg.price / long_leg.price - 1.0) * 10_000.0
    total_cost = (
        max(0.0, long_leg.fee_bps)
        + max(0.0, short_leg.fee_bps)
        + max(0.0, long_leg.slippage_bps)
        + max(0.0, short_leg.slippage_bps)
    )
    mos = evaluate_margin_of_safety(gross_edge_bps=gross, total_cost_bps=total_cost, config=margin_config)
    return PaperArbitrageOpportunity(
        accepted=mos.accepted,
        coin=long_leg.coin.upper(),
        long_source=long_leg.source,
        short_source=short_leg.source,
        gross_spread_bps=round(gross, 8),
        total_cost_bps=round(total_cost, 8),
        net_edge_bps=mos.net_edge_bps,
        reason_codes=mos.reason_codes,
    )


__all__ = ["PaperArbitrageLeg", "PaperArbitrageOpportunity", "build_paper_arbitrage_opportunity"]
