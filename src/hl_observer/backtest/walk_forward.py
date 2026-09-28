from __future__ import annotations

import math


def split_walk_forward(items: list, train_fraction: float = 0.7) -> tuple[list, list]:
    if (isinstance(train_fraction, bool) or not math.isfinite(float(train_fraction))
            or not 0.0 < float(train_fraction) < 1.0):
        raise ValueError("train_fraction must be finite and in (0, 1)")
    cut = int(len(items) * float(train_fraction))
    if cut < 1 or cut >= len(items):
        raise ValueError("walk-forward split requires non-empty train and test sets")
    return items[:cut], items[cut:]
