"""V13 #154 — fast/slow/blend volatility sigma (mlmodelpoly)."""

from __future__ import annotations

from math import sqrt


def _std(xs: list[float]) -> float:
    xs = [float(x) for x in xs]
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def sigma_fast_slow_blend(returns: list[float], *, fast_n: int = 20, slow_n: int = 100,
                          blend_w: float = 0.5) -> dict:
    r = [float(x) for x in (returns or [])]
    fast = _std(r[-fast_n:]) if len(r) >= 2 else 0.0
    slow = _std(r[-slow_n:]) if len(r) >= 2 else 0.0
    w = max(0.0, min(1.0, float(blend_w)))
    blend = w * fast + (1.0 - w) * slow
    return {"sigma_fast": round(fast, 8), "sigma_slow": round(slow, 8), "sigma_blend": round(blend, 8)}


__all__ = ["sigma_fast_slow_blend"]
