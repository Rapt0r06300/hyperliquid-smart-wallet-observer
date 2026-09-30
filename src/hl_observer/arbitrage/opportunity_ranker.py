"""Rank paper-only arbitrage opportunities by net edge."""

from __future__ import annotations

from hl_observer.arbitrage.opportunity_model import PaperArbitrageOpportunity


def rank_paper_arbitrage_opportunities(
    opportunities: list[PaperArbitrageOpportunity],
    *,
    accepted_only: bool = True,
    limit: int | None = None,
) -> list[PaperArbitrageOpportunity]:
    rows = [row for row in opportunities if (row.accepted or not accepted_only)]
    rows.sort(key=lambda row: (row.accepted, row.net_edge_bps, row.gross_spread_bps), reverse=True)
    return rows[:limit] if limit is not None else rows


__all__ = ["rank_paper_arbitrage_opportunities"]
