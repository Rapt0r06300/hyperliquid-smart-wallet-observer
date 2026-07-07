"""Funding spike detector for paper arbitrage/funding scans."""

from __future__ import annotations

from dataclasses import dataclass

from hl_observer.funding.funding_history_window import funding_window_stats


@dataclass(frozen=True, slots=True)
class FundingSpikeDecision:
    spike: bool
    z_score: float | None
    reason: str | None


def detect_funding_spike(rates: list[float], *, sigma: float = 2.0) -> FundingSpikeDecision:
    stats = funding_window_stats(rates)
    if stats.z_score is None:
        return FundingSpikeDecision(False, None, "FUNDING_HISTORY_INSUFFICIENT")
    if abs(stats.z_score) >= float(sigma):
        return FundingSpikeDecision(True, stats.z_score, "FUNDING_SPIKE")
    return FundingSpikeDecision(False, stats.z_score, None)


__all__ = ["FundingSpikeDecision", "detect_funding_spike"]
