"""Close four pure coverage gaps without touching runtime behavior or external I/O."""

from hl_observer.arbitrage.per_leg_shortfall import UNMEASURABLE, shortfall_bps
from hl_observer.backtesting.market_metrics import oi_change
from hl_observer.backtesting.portfolio_risk import correlation
from hl_observer.features.feature_normalize import clamp_outliers


def test_pure_fail_closed_micro_gaps() -> None:
    assert oi_change([42.0]) == 0.0
    assert correlation([1.0], [2.0]) == 0.0
    assert shortfall_bps(101.0, 100.0, "UNKNOWN_SIDE") == UNMEASURABLE
    assert clamp_outliers([1.0, 1.0, 2.0]) == [1.0, 1.0, 2.0]
