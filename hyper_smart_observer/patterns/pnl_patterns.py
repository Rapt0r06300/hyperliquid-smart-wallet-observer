from __future__ import annotations


def pnl_is_concentrated(pnls: list[float], threshold: float = 0.5) -> bool:
    total = sum(abs(value) for value in pnls)
    return bool(total and max(abs(value) for value in pnls) / total > threshold)
