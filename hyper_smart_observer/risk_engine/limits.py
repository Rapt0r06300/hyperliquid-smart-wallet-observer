from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    min_wallet_score: float = 70.0
    min_confidence: float = 0.6
    min_sample_size: int = 30
    max_open_paper_trades: int = 3
    max_paper_notional: float = 100.0
