from __future__ import annotations


def clamp_paper_size(size_usdc: float, *, max_size_usdc: float) -> float:
    return max(0.0, min(size_usdc, max_size_usdc))
