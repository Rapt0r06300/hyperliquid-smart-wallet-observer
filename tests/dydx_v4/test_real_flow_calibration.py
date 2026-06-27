from __future__ import annotations

from hyper_smart_observer.dydx_v4.config import DydxV4Config
from hyper_smart_observer.dydx_v4.real_flow_calibration import (
    apply_real_flow_calibration,
    real_flow_summary,
)


def test_real_flow_calibration_expands_real_public_trade_recall() -> None:
    cfg = apply_real_flow_calibration(DydxV4Config())
    summary = real_flow_summary(cfg)

    assert summary["market_flow_enabled"] is True
    assert summary["market_flow_min_volume_usdc"] <= 2500.0
    assert summary["market_flow_min_imbalance"] <= 0.54
    assert summary["flow_min_trades"] <= 2
    assert summary["allow_market_flow_solo_entries"] is False
    assert summary["source"] == "REAL_PUBLIC_DYDX_TRADES"
    assert summary["read_only"] is True
    assert summary["paper_only"] is True
