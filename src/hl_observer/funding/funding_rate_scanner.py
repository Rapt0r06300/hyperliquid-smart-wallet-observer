"""Funding-rate signal scanner for paper simulations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .spike_detector import detect_funding_spike


@dataclass(frozen=True, slots=True)
class FundingSignal:
    coin: str
    decision: str
    z_score: float | None
    reason: str | None


def scan_funding_rates(rows: Iterable[dict[str, object]], *, sigma: float = 2.0) -> tuple[FundingSignal, ...]:
    out: list[FundingSignal] = []
    for row in rows:
        rates = [float(x) for x in row.get("rates", [])]
        decision = detect_funding_spike(rates, sigma=sigma)
        out.append(FundingSignal(str(row.get("coin") or "").upper(), "FUNDING_SPIKE" if decision.spike else "NO_TRADE", decision.z_score, decision.reason))
    return tuple(out)


__all__ = ["FundingSignal", "scan_funding_rates"]
