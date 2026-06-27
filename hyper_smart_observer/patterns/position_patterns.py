from __future__ import annotations


def count_action_types(actions: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for action in actions:
        counts[action] = counts.get(action, 0) + 1
    return counts
