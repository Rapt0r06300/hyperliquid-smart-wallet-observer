from __future__ import annotations

from hl_observer.backtesting.cross_venue_v3_train import replay_variant_train


def _atomic(ts: int, hl_mid: float, bin_mid: float) -> tuple:
    half = 0.005
    return (
        ts,
        "ATOMIC",
        hl_mid - half,
        hl_mid + half,
        bin_mid - half,
        bin_mid + half,
    )


def test_cross_v3_rejoue_impulsion_puis_entree_retardee_et_quatre_fills() -> None:
    start = 1_800_000_000_000
    series = {
        "BTC": [
            _atomic(start, 100.0, 100.0),
            _atomic(start + 1_000, 100.10, 100.0),
            _atomic(start + 1_400, 100.10, 100.0),
            _atomic(start + 2_500, 100.05, 100.05),
        ]
    }
    depth = {
        "BTC": [(row[0], 1_000.0) for row in series["BTC"]],
    }

    trades, diagnostics = replay_variant_train(
        series,
        depth,
        leader_threshold_bps=8.0,
        max_hold_ms=10_000,
        train_end_ms=start + 20_000,
    )

    assert diagnostics["CLOSED_LIQUIDATABLE_TRADE"] == 1
    assert len(trades) == 1
    trade = trades[0]
    assert trade["leader_venue"] == "HL"
    assert trade["entry_ts_ms"] == start + 1_400
    assert trade["exit_ts_ms"] == start + 2_500
    assert trade["four_fills_complete"] is True
    assert trade["two_leg"] is True
    assert trade["LIQUIDATABLE_NET"] is True
    assert trade["economic_reconciliation_ok"] is True
    assert trade["real_execution"] is False
