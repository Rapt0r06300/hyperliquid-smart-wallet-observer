from __future__ import annotations

from pydantic import BaseModel


class TradeLifecycle(BaseModel):
    wallet_address: str
    coin: str
    side: str | None = None
    status: str = "OPEN"
    realized_pnl_usdc: float | None = None
    confidence_score: float = 0.0
