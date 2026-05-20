from __future__ import annotations

from pydantic import BaseModel


class RiskContext(BaseModel):
    spread_bps: float
    estimated_slippage_bps: float
    orderbook_depth_usdc: float
    wallet_score: float
    signal_score: float
    edge_remaining_bps: float
    signal_age_ms: int
    duplicate_order_risk: bool = False
    data_gap: bool = False
    api_unstable: bool = False
    ws_recently_reconnected: bool = False
    reconciliation_uncertain: bool = False
    kill_switch_active: bool = False
