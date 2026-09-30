from hl_observer.signals.fill_admission import (
    FillAdmissionConfig,
    admit_live_fill,
    fill_identity,
    KIND_ENTRY,
    KIND_EXIT,
    KIND_SKIP,
    R_FRESH_ENTRY,
    R_FRESH_EXIT,
    R_STALE_BACKFILL,
    R_DUPLICATE,
    R_NO_POSITION_FOR_EXIT,
    R_EXOTIC_MARKET,
    R_ADD_NOT_ENTRY,
    R_UNKNOWN_DELTA,
    R_STALE_SIGNAL,
)

NOW = 1_000_000_000


def _admit(**kw):
    base = dict(
        action_type="OPEN_LONG",
        coin="BTC",
        fill_ts_ms=NOW - 3_000,
        now_ms=NOW,
        already_seen=False,
        has_matching_paper_position=False,
    )
    base.update(kw)
    return admit_live_fill(**base)


def test_fresh_open_is_admitted_as_entry():
    d = _admit(action_type="OPEN_LONG", fill_ts_ms=NOW - 3_000)
    assert d.admit is True and d.kind == KIND_ENTRY and d.reason == R_FRESH_ENTRY
    assert d.is_fresh is True and d.log_decision is True
    assert d.execution == "forbidden"


def test_fresh_add_is_entry_when_allowed():
    d = _admit(action_type="ADD")
    assert d.admit is True and d.kind == KIND_ENTRY


def test_add_not_entry_when_disabled_and_flat_is_silent_skip():
    cfg = FillAdmissionConfig(allow_add_as_entry=False)
    d = _admit(action_type="ADD", has_matching_paper_position=False, config=cfg)
    assert d.admit is False and d.kind == KIND_SKIP
    assert d.reason == R_ADD_NOT_ENTRY and d.log_decision is False


def test_stale_backfill_is_silent_skip():
    d = _admit(action_type="OPEN_LONG", fill_ts_ms=NOW - 5 * 3_600_000)  # 5h
    assert d.admit is False and d.reason == R_STALE_BACKFILL and d.log_decision is False


def test_stale_entry_before_backfill_is_refused_before_scoring():
    cfg = FillAdmissionConfig(max_signal_age_ms=15_000, hard_backfill_age_ms=30_000)
    d = _admit(action_type="OPEN_LONG", fill_ts_ms=NOW - 20_000, config=cfg)
    assert d.admit is False and d.reason == R_STALE_SIGNAL
    assert d.log_decision is True and d.kind == KIND_SKIP


def test_duplicate_fill_is_silent_skip():
    d = _admit(already_seen=True)
    assert d.admit is False and d.reason == R_DUPLICATE and d.log_decision is False


def test_exotic_market_is_silent_skip():
    for coin in ["XYZ:TSLA", "CASH:WTI", "@107", "#2160"]:
        d = _admit(coin=coin)
        assert d.admit is False and d.reason == R_EXOTIC_MARKET and d.log_decision is False, coin


def test_exit_without_position_is_silent_skip_no_noise():
    d = _admit(action_type="REDUCE", has_matching_paper_position=False)
    assert d.admit is False and d.reason == R_NO_POSITION_FOR_EXIT and d.log_decision is False


def test_exit_with_position_is_admitted_as_exit():
    d = _admit(action_type="CLOSE_LONG", has_matching_paper_position=True)
    assert d.admit is True and d.kind == KIND_EXIT and d.reason == R_FRESH_EXIT


def test_unknown_delta_is_silent_skip():
    d = _admit(action_type="WHATEVER")
    assert d.admit is False and d.reason == R_UNKNOWN_DELTA


def test_fill_identity_is_stable_and_distinct():
    a = fill_identity(wallet_address="0xABC", coin="BTC", side="LONG", action_type="ADD", price=100.0, size=1.0, ts_ms=NOW)
    b = fill_identity(wallet_address="0xabc", coin="btc", side="long", action_type="add", price=100.0, size=1.0, ts_ms=NOW)
    c = fill_identity(wallet_address="0xABC", coin="BTC", side="LONG", action_type="ADD", price=100.0, size=2.0, ts_ms=NOW)
    assert a == b  # normalisation casse/charset
    assert a != c  # taille différente -> identité différente


def test_replay_on_realistic_mix_drops_the_noise():
    """Sur un mix réaliste (comme les logs), seules les ENTRÉES/SORTIES propres
    sont admises ; le bruit (backfill, exotiques, close-sans-position) est sauté
    sans être loggé."""
    now = NOW
    fills = (
        # entrées fraîches propres -> admises
        [dict(action_type="OPEN_LONG", coin="BTC", fill_ts_ms=now - 2_000)] * 3
        + [dict(action_type="ADD", coin="HYPE", fill_ts_ms=now - 4_000)] * 2
        # bruit : close-sans-position
        + [dict(action_type="REDUCE", coin="BTC", fill_ts_ms=now - 2_000, has_matching_paper_position=False)] * 50
        # bruit : exotiques
        + [dict(action_type="OPEN_LONG", coin="XYZ:TSLA", fill_ts_ms=now - 2_000)] * 20
        # bruit : backfill
        + [dict(action_type="OPEN_LONG", coin="ETH", fill_ts_ms=now - 6 * 3_600_000)] * 30
    )
    admitted = logged = 0
    for f in fills:
        base = dict(now_ms=now, already_seen=False, has_matching_paper_position=False)
        base.update(f)
        d = admit_live_fill(**base)
        admitted += int(d.admit)
        logged += int(d.log_decision)
    assert admitted == 5  # 3 OPEN BTC + 2 ADD HYPE
    assert logged == 5    # le bruit (100 lignes) n'est PAS loggé
