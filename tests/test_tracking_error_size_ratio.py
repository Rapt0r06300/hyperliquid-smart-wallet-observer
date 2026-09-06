import pytest

from hl_observer.copy_fidelity.tracking_error import CopyTrade, trade_fidelity


def test_trade_fidelity_reports_copy_to_leader_size_ratio() -> None:
    fidelity = trade_fidelity(
        CopyTrade(
            "long",
            leader_price=100.0,
            copy_price=100.5,
            leader_size=4.0,
            copy_size=1.0,
        )
    )

    assert fidelity.size_ratio == pytest.approx(0.25)
