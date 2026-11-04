from __future__ import annotations

from math import isfinite

from hl_observer.utils.math import clamp


def wallet_toxicity_score(drawdown_bps: float, concentration: float, slippage_bps: float) -> float:
    return clamp((drawdown_bps / 1000.0) + concentration + (slippage_bps / 50.0), 0.0, 1.0)


def jackpot_robustness_receipt(
    *,
    top_trade_pnl_share: float,
    leverage: float,
    max_leverage: float = 5.0,
    max_top_trade_share: float = 0.30,
) -> dict[str, object]:
    """Reject a score whose result depends on a jackpot or extreme leverage."""
    values = (top_trade_pnl_share, leverage, max_leverage, max_top_trade_share)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value))
           for value in values):
        return {"status": "UNMEASURABLE", "reason": "non_finite_numeric_observation"}
    if any(value < 0 for value in values) or max_leverage <= 0 or max_top_trade_share <= 0:
        return {"status": "UNMEASURABLE", "reason": "invalid_robustness_bounds"}
    robust = top_trade_pnl_share <= max_top_trade_share and leverage <= max_leverage
    return {
        "status": "PROVEN",
        "robust": robust,
        "decision": "ROBUST" if robust else "REJECT_EXTREME",
        "top_trade_pnl_share": float(top_trade_pnl_share),
        "leverage": float(leverage),
        "max_top_trade_share": float(max_top_trade_share),
        "max_leverage": float(max_leverage),
    }
