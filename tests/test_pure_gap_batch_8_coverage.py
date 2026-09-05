from __future__ import annotations

from hl_observer.simulation.funding_payment_tracker import compute_funding_payment_usdc


def test_unknown_funding_side_fails_closed_to_zero() -> None:
    assert compute_funding_payment_usdc(
        side="FLAT",
        notional_usdc=1_000.0,
        funding_rate=0.0001,
        intervals=2,
    ) == 0.0
