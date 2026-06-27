"""MarketMid provenance + quality fallback, and refusal of a missing mid.

derive_market_mid labels every mid MID_FROM_BOOK / MID_FROM_LAST_TRADE_FALLBACK /
MID_MISSING with explicit data_quality. A missing/invalid current_mid must force a
NoTrade (EDGE_UNMEASURABLE) in build_signal_candidate. No network, deterministic.
"""

from __future__ import annotations

from hyper_smart_observer.copy_mode.copy_models import PositionView, utc_now
from hyper_smart_observer.copy_mode.delta_detector import diff_position_snapshots
from hyper_smart_observer.copy_mode.signal_candidate import build_signal_candidate
from hyper_smart_observer.market_signals.mid_stability import derive_market_mid

ADDR = "0x" + "e" * 40


def test_mid_from_book():
    m = derive_market_mid("btc", best_bid=100.0, best_ask=100.5)
    assert m.mid_source == "MID_FROM_BOOK"
    assert m.mid == 100.25 and m.source_endpoint == "l2Book"
    assert m.data_quality == "OK" and m.is_stale is False


def test_mid_from_allmids_when_no_book():
    m = derive_market_mid("BTC", all_mids={"BTC": "100.2"})
    assert m.mid_source == "MID_FROM_BOOK" and m.source_endpoint == "allMids"
    assert m.mid == 100.2


def test_mid_from_last_trade_fallback_is_degraded():
    m = derive_market_mid("BTC", last_trade_price="99.9")
    assert m.mid_source == "MID_FROM_LAST_TRADE_FALLBACK"
    assert m.data_quality == "DEGRADED" and m.source_endpoint == "trades"


def test_mid_missing_when_no_source():
    m = derive_market_mid("BTC")
    assert m.mid_source == "MID_MISSING"
    assert m.mid is None and m.data_quality == "MISSING" and m.is_stale is True


def test_stale_book_mid_is_flagged():
    m = derive_market_mid("BTC", best_bid=100.0, best_ask=100.5, is_stale=True)
    assert m.mid_source == "MID_FROM_BOOK"
    assert m.data_quality == "STALE" and m.is_stale is True


def _open_long_delta():
    now = utc_now()
    return diff_position_snapshots(
        [PositionView(ADDR, "BTC", 0, now, 50_000)],
        [PositionView(ADDR, "BTC", 1, now, 50_010)],
        observed_at=now,
    )[0]


def test_missing_mid_forces_no_trade_edge_unmeasurable():
    signal = build_signal_candidate(
        _open_long_delta(),
        leader_expected_edge_bps=100.0,
        current_mid=None,  # MID_MISSING
        leader_score=95,
    )
    assert signal.decision.value == "REJECT_NO_TRADE"
    assert "EDGE_UNMEASURABLE" in signal.refusal_reasons


def test_present_mid_does_not_trigger_edge_unmeasurable():
    signal = build_signal_candidate(
        _open_long_delta(),
        leader_expected_edge_bps=100.0,
        current_mid=50_000.0,
        leader_score=95,
        spread_bps=2.0,
        slippage_bps=5.0,
        liquidity_score=1.0,
    )
    assert "EDGE_UNMEASURABLE" not in signal.refusal_reasons
