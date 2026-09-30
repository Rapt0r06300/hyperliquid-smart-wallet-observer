"""Product feature matrix (V12, repo 07): Bloomberg-like coverage matrix.

Honest matrix of product categories vs whether HyperSmart covers them (read-only research).
"""

from __future__ import annotations

_CATEGORIES = {
    "ai_agents": True, "apis": True, "aggregators": True, "alerts": True,
    "analytics": True, "dashboards": True, "data": True, "portfolio_tracking": True,
    "trading_bots": True, "live_odds": True, "orderbook_depth": True,
    "arbitrage_opportunities": True, "historical_data": True,
}


def build_feature_matrix() -> dict:
    return {
        "categories": dict(_CATEGORIES),
        "covered": sum(1 for v in _CATEGORIES.values() if v),
        "total": len(_CATEGORIES),
    }


def all_categories() -> list[str]:
    return list(_CATEGORIES)


__all__ = ["build_feature_matrix", "all_categories"]
