from hl_observer.signals.eligibility import (
    STATUS_LOW_EDGE,
    STATUS_OK,
    STATUS_STALE,
    STATUS_WIDE_SPREAD,
    EligibilityConfig,
    EntryCooldownTracker,
    check_entry_eligibility,
    describe_signal,
)


def test_first_entry_is_eligible():
    r = check_entry_eligibility(coin="BTC", now_sec=1000, recent_entry_times_sec=[])
    assert r.eligible and r.reason == "ELIGIBLE"


def test_cooldown_blocks_quick_reentry():
    cfg = EligibilityConfig(cooldown_sec=60)
    r = check_entry_eligibility(coin="BTC", now_sec=1030, recent_entry_times_sec=[1000], config=cfg)
    assert r.blocked
    assert r.reason == "ENTRY_COOLDOWN_ACTIVE"
    assert r.seconds_until_eligible == 30.0


def test_cooldown_clears_after_delay():
    cfg = EligibilityConfig(cooldown_sec=60)
    r = check_entry_eligibility(coin="BTC", now_sec=1061, recent_entry_times_sec=[1000], config=cfg)
    assert r.eligible


def test_max_entries_per_window():
    cfg = EligibilityConfig(cooldown_sec=1, max_entries_per_window=3, window_sec=900)
    # 3 entries already inside the window -> 4th blocked
    r = check_entry_eligibility(coin="BTC", now_sec=1000,
                                recent_entry_times_sec=[200, 500, 800], config=cfg)
    assert r.blocked
    assert r.reason == "MAX_ENTRIES_PER_WINDOW"


def test_old_entries_drop_out_of_window():
    cfg = EligibilityConfig(cooldown_sec=1, max_entries_per_window=3, window_sec=900)
    # entries older than the window don't count
    r = check_entry_eligibility(coin="BTC", now_sec=5000,
                                recent_entry_times_sec=[200, 500, 800], config=cfg)
    assert r.eligible


def test_signal_shape_status_ok():
    s = describe_signal(coin="btc", action="add", edge_bps=20, spread_bps=3, age_sec=5)
    assert s.status == STATUS_OK and s.is_actionable
    assert s.coin == "BTC" and s.action == "ADD"


def test_signal_shape_stale_wins_first():
    s = describe_signal(coin="BTC", action="ADD", edge_bps=1, spread_bps=999, age_sec=99,
                        max_age_sec=30)
    assert s.status == STATUS_STALE  # staleness checked first


def test_signal_shape_low_edge():
    s = describe_signal(coin="BTC", action="ADD", edge_bps=2, spread_bps=3, age_sec=5,
                        min_edge_bps=10)
    assert s.status == STATUS_LOW_EDGE and not s.is_actionable


def test_signal_shape_wide_spread():
    s = describe_signal(coin="BTC", action="ADD", edge_bps=20, spread_bps=80, age_sec=5,
                        max_spread_bps=50)
    assert s.status == STATUS_WIDE_SPREAD


def test_cooldown_tracker_stateful():
    cfg = EligibilityConfig(cooldown_sec=60, max_entries_per_window=5)
    t = EntryCooldownTracker(cfg)
    assert t.check("BTC", 1000).eligible
    t.register_entry("BTC", 1000)
    assert t.check("BTC", 1030).blocked          # within cooldown
    assert t.check("ETH", 1030).eligible         # different coin unaffected
    assert t.check("BTC", 1100).eligible          # cooldown elapsed


def test_tracker_no_execution_surface():
    t = EntryCooldownTracker()
    public = {n for n in dir(t) if not n.startswith("_")}
    for forbidden in ("submit", "place", "order", "sign", "send"):
        assert not any(forbidden in n.lower() for n in public)
