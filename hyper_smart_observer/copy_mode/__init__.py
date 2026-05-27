"""Research-only copy observation mode.

This package implements the "magic bot" architecture as a safe local observer:
leader shortlist, delta detection, edge degradation, no-trade reporting and
paper/mock-USDC simulation hooks. It never executes orders.
"""

from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run
from hyper_smart_observer.copy_mode.delta_detector import classify_fill_delta, classify_position_delta
from hyper_smart_observer.copy_mode.edge import compute_edge_remaining_bps
from hyper_smart_observer.copy_mode.consensus import detect_position_consensus
from hyper_smart_observer.copy_mode.leaderboard_selector import select_leaderboard_shortlist
from hyper_smart_observer.copy_mode.sizing import calculate_paper_copy_sizing

__all__ = [
    "calculate_paper_copy_sizing",
    "classify_fill_delta",
    "classify_position_delta",
    "compute_edge_remaining_bps",
    "detect_position_consensus",
    "run_copy_dry_run",
    "select_leaderboard_shortlist",
]
