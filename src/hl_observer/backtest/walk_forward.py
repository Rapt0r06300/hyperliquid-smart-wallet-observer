from __future__ import annotations


def split_walk_forward(items: list, train_fraction: float = 0.7) -> tuple[list, list]:
    cut = int(len(items) * train_fraction)
    return items[:cut], items[cut:]
