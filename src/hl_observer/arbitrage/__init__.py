"""Paper-only arbitrage and funding opportunity models."""

from hl_observer.arbitrage.cross_source_comparator import CrossSourceDiscrepancy, CrossSourcePrice, compare_cross_source_prices
from hl_observer.arbitrage.funding_adjusted_edge import FundingAdjustedEdge, funding_adjusted_edge_bps
from hl_observer.arbitrage.hyperliquid_cex_spread_scanner import CrossExchangeOpportunity, scan_hyperliquid_cex_spread
from hl_observer.arbitrage.opportunity_model import (
    PaperArbitrageLeg,
    PaperArbitrageOpportunity,
    build_paper_arbitrage_opportunity,
)
from hl_observer.arbitrage.orderbook_snapshot import OrderBookSnapshot
from hl_observer.arbitrage.opportunity_ranker import rank_paper_arbitrage_opportunities
from hl_observer.arbitrage.path_cost_model import PathCost, path_cost_bps
from hl_observer.arbitrage.spread_formula import CrossExchangeSpread, compute_cross_exchange_spread
from hl_observer.arbitrage.symbol_normalizer import normalize_symbol
from hl_observer.arbitrage.triangular_graph import TriangularEdge, build_triangular_cycles
from hl_observer.arbitrage.triangular_opportunity_detector import (
    TriangularOpportunity,
    detect_triangular_opportunities,
)

__all__ = [
    "CrossSourcePrice",
    "CrossSourceDiscrepancy",
    "FundingAdjustedEdge",
    "CrossExchangeOpportunity",
    "CrossExchangeSpread",
    "PathCost",
    "OrderBookSnapshot",
    "PaperArbitrageLeg",
    "PaperArbitrageOpportunity",
    "TriangularEdge",
    "TriangularOpportunity",
    "build_paper_arbitrage_opportunity",
    "build_triangular_cycles",
    "compare_cross_source_prices",
    "compute_cross_exchange_spread",
    "detect_triangular_opportunities",
    "funding_adjusted_edge_bps",
    "normalize_symbol",
    "path_cost_bps",
    "rank_paper_arbitrage_opportunities",
    "scan_hyperliquid_cex_spread",
]
