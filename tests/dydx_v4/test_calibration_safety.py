from __future__ import annotations

from hyper_smart_observer.dydx_v4.config import DydxV4Config
from hyper_smart_observer.dydx_v4.opportunity_calibration import apply_opportunity_calibration


def test_calibration_keeps_read_only_paper_only() -> None:
    cfg = apply_opportunity_calibration(DydxV4Config())

    assert cfg.read_only is True
    assert cfg.paper_only is True
    assert cfg.allow_trading is False
    assert cfg.allow_private_key is False
