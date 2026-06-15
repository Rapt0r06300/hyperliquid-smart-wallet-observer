from __future__ import annotations


def test_wide_scan_targets_are_large_enough() -> None:
    from hyper_smart_observer.dydx_v4.leaderboard_import_patch import HOT_WALLET_TARGET, WIDE_TRACK_TARGET

    assert HOT_WALLET_TARGET >= 2500
    assert WIDE_TRACK_TARGET >= 15000


def test_wide_scan_pool_rotates_candidates() -> None:
    from hyper_smart_observer.dydx_v4.wide_scan_pool import select_rotating_wallets

    pairs = [(f"wallet{i}", float(10000 - i)) for i in range(1000)]
    first = select_rotating_wallets(pairs, hot_capacity=100, rotate_batch=20, cursor=0, anchor_share=0.5)
    second = select_rotating_wallets(pairs, hot_capacity=100, rotate_batch=20, cursor=first.next_cursor, anchor_share=0.5)

    assert len(first.selected) == 70
    assert len(second.selected) == 70
    assert first.next_cursor != second.next_cursor
    assert set(first.selected) != set(second.selected)
