from __future__ import annotations

from typing import Any

from hl_observer.arbitrage.hyperliquid_cex_spread_scanner import CrossExchangeOpportunity


def build_arbitrage_panel(opportunities: list[CrossExchangeOpportunity]) -> dict[str, Any]:
    rows = [item.as_dict() for item in opportunities]
    return {
        "title": "Cross-source paper arbitrage",
        "accepted": sum(1 for item in opportunities if item.decision == "ACCEPT_PAPER_ARBITRAGE"),
        "no_trade": sum(1 for item in opportunities if item.decision != "ACCEPT_PAPER_ARBITRAGE"),
        "rows": rows,
        "paper_only": True,
        "real_execution": False,
    }


__all__ = ["build_arbitrage_panel"]
