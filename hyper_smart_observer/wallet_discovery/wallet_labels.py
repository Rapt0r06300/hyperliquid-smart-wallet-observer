from __future__ import annotations


def label_wallet(candidate_score: float) -> str:
    if candidate_score >= 75:
        return "research_priority"
    if candidate_score >= 40:
        return "watchlist_candidate"
    return "observe_only"
