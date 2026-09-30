from __future__ import annotations


def followability_score(*, liquidity_score: float, pattern_score: float, latency_penalty: float = 0.0) -> float:
    return max(0.0, min(100.0, 0.45 * liquidity_score + 0.55 * pattern_score - latency_penalty))
