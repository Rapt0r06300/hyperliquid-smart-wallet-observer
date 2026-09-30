from __future__ import annotations


def leader_reduced_position(previous_size: float, current_size: float) -> bool:
    return abs(current_size) < abs(previous_size)
