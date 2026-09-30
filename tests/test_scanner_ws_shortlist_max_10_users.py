"""WS user-specific stream cap: at most 10 wallets, controlled trimming, no loop.

Hyperliquid rate limits forbid following all wallets in WS. The hot-watch
rotation hard-caps at 10 user-specific streams; the watchlist manager refuses
beyond 10. Read-only, deterministic, no network.
"""

from __future__ import annotations

import pytest

from hyper_smart_observer.realtime_monitor.hot_watch_rotation import rotate_hot_watch
from hyper_smart_observer.realtime_monitor.watchlist_manager import WatchlistManager


def test_hot_watch_caps_user_streams_at_ten_even_if_more_requested():
    candidates = [("0x" + f"{i:040x}", float(i), 1_800_000_000_000) for i in range(1, 26)]
    slots = rotate_hot_watch(candidates, now_ms=1_800_000_000_000, max_slots=50)
    assert len(slots) == 10  # hard cap regardless of requested max
    wallets = [s.wallet_address for s in slots]
    assert len(set(wallets)) == 10  # no duplicate streams
    assert slots[0].priority >= slots[-1].priority  # deterministic, terminates


def test_watchlist_manager_refuses_more_than_ten():
    wm = WatchlistManager(max_wallets=10)
    for i in range(10):
        assert wm.add("0x" + f"{i:040x}") is True
    with pytest.raises(ValueError):
        wm.add("0x" + "f" * 40)
    assert len(wm.wallets) == 10


def test_hot_watch_empty_when_no_candidates():
    assert rotate_hot_watch([], now_ms=1, max_slots=10) == []
