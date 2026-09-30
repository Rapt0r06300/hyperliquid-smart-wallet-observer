from __future__ import annotations

from hl_observer.utils.math import clamp


def wallet_toxicity_score(drawdown_bps: float, concentration: float, slippage_bps: float) -> float:
    return clamp((drawdown_bps / 1000.0) + concentration + (slippage_bps / 50.0), 0.0, 1.0)
