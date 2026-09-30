"""Research-only copy observation mode.

This package implements the safe local observer architecture: leaderboard,
delta detection, edge degradation, no-trade reporting and paper/mock-USDC hooks.
Imports are intentionally lazy so low-level modules (for example the paper exit
engine) can import copy-mode models without pulling the full copy loop and
creating circular imports. It never executes orders.
"""

__all__ = [
    "calculate_paper_copy_sizing",
    "classify_fill_delta",
    "classify_position_delta",
    "compute_edge_remaining_bps",
    "detect_position_consensus",
    "run_copy_dry_run",
    "select_leaderboard_shortlist",
]


def __getattr__(name):
    if name == "calculate_paper_copy_sizing":
        from hyper_smart_observer.copy_mode.sizing import calculate_paper_copy_sizing
        return calculate_paper_copy_sizing
    if name == "classify_fill_delta":
        from hyper_smart_observer.copy_mode.delta_detector import classify_fill_delta
        return classify_fill_delta
    if name == "classify_position_delta":
        from hyper_smart_observer.copy_mode.delta_detector import classify_position_delta
        return classify_position_delta
    if name == "compute_edge_remaining_bps":
        from hyper_smart_observer.copy_mode.edge import compute_edge_remaining_bps
        return compute_edge_remaining_bps
    if name == "detect_position_consensus":
        from hyper_smart_observer.copy_mode.consensus import detect_position_consensus
        return detect_position_consensus
    if name == "run_copy_dry_run":
        from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run
        return run_copy_dry_run
    if name == "select_leaderboard_shortlist":
        from hyper_smart_observer.copy_mode.leaderboard_selector import select_leaderboard_shortlist
        return select_leaderboard_shortlist
    raise AttributeError(name)
