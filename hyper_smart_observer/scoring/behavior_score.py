from __future__ import annotations


def behavior_stability_score(*, actions_count: int, unknown_actions: int) -> float:
    if actions_count <= 0:
        return 0.0
    unknown_ratio = unknown_actions / actions_count
    return max(0.0, min(100.0, 100.0 * (1.0 - unknown_ratio)))
