from __future__ import annotations


def test_subaccount_scan_depth_constants() -> None:
    from hyper_smart_observer.dydx_v4.leaderboard_import_patch import (
        HOT_WALLET_TARGET,
        SUBACCOUNT_DEPTH,
        WIDE_TRACK_TARGET,
    )

    assert WIDE_TRACK_TARGET >= 15000
    assert HOT_WALLET_TARGET >= 2500
    assert SUBACCOUNT_DEPTH >= 4
    assert HOT_WALLET_TARGET * SUBACCOUNT_DEPTH >= 10000
