from __future__ import annotations

from pydantic import BaseModel


class OpeningOutcome(BaseModel):
    wallet_address: str
    coin: str
    opening_type: str
    pnl_usdc: float | None = None
    roi_pct: float | None = None
    hold_time_ms: int | None = None
    confidence_score: float = 0.0


def compute_opening_outcome(*, wallet_address: str, coin: str, opening_type: str, closed_pnl: float | None) -> OpeningOutcome:
    return OpeningOutcome(
        wallet_address=wallet_address,
        coin=coin.upper(),
        opening_type=opening_type,
        pnl_usdc=closed_pnl,
        roi_pct=None,
        confidence_score=0.5 if closed_pnl is not None else 0.2,
    )
