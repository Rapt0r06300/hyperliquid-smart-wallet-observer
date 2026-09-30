from __future__ import annotations

import pytest

from hl_observer.paper_trading.funding_settlement import decouper


def test_negative_funding_period_is_kept_estimated() -> None:
    position = {
        "funding_accrued_usdt": 0.25,
        "entry_ts_ms": 1_000,
    }

    result = decouper(position, now_ms=2_000, periode_ms=-3_600_000)

    assert result["net_funding_settled"] == 0.0
    assert result["funding_accrual_estimate"] == pytest.approx(0.25)
    assert result["heures_reglees"] == 0.0
