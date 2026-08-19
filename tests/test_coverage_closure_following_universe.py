from __future__ import annotations

import importlib

from hl_observer.analysis.followability import followability_score
from hl_observer.analysis.opening_outcome import OpeningOutcome, compute_opening_outcome
from hl_observer.analysis.trade_lifecycle import TradeLifecycle
from hl_observer.following.follow_reconciliation import reconcile_follow_signal
from hl_observer.following.follow_state import FollowState
from hl_observer.following.leaderboard_follow_shortlist import load_leaderboard_follow_shortlist
from hl_observer.monitoring.monitor_output import build_monitor_output
from hl_observer.runtime.safe_mode import is_safe_mode_enabled
from hl_observer.universe.blacklist import filter_blacklisted
from hl_observer.universe.dynamic_whitelist import build_dynamic_whitelist
from hl_observer.wallets.degradation import wallet_degraded


def test_opening_outcome_and_lifecycle_models() -> None:
    closed = compute_opening_outcome(wallet_address="0xA", coin="btc", opening_type="OPEN_LONG", closed_pnl=3.0)
    assert isinstance(closed, OpeningOutcome)
    assert closed.coin == "BTC" and closed.pnl_usdc == 3.0 and closed.confidence_score == 0.5
    pending = compute_opening_outcome(wallet_address="0xB", coin="eth", opening_type="OPEN_SHORT", closed_pnl=None)
    assert pending.coin == "ETH" and pending.pnl_usdc is None and pending.confidence_score == 0.2
    lifecycle = TradeLifecycle(wallet_address="0xA", coin="BTC")
    assert lifecycle.status == "OPEN" and lifecycle.side is None and lifecycle.realized_pnl_usdc is None


def test_follow_state_has_isolated_default_dict() -> None:
    one = FollowState()
    two = FollowState()
    one.active_signals["a"] = "BTC"
    assert one.mode == "OBSERVE_ONLY"
    assert two.active_signals == {}


def test_dynamic_universe_and_blacklist() -> None:
    markets = [
        {"coin": "btc", "volume_usdt": 200_000, "depth_usdt": 20_000},
        {"coin": "ETH", "volume_usdt": 200_000, "depth_usdt": 20_000},
        {"coin": "btc", "volume_usdt": 300_000, "depth_usdt": 30_000},
        {"coin": "SOL", "volume_usdt": 99_999, "depth_usdt": 20_000},
        {"coin": "DOGE", "volume_usdt": 200_000, "depth_usdt": 9_999},
        {"coin": "", "volume_usdt": 999_999, "depth_usdt": 999_999},
    ]
    assert build_dynamic_whitelist(markets) == ("BTC", "ETH")
    assert build_dynamic_whitelist([], min_volume_usdt=0, min_depth_usdt=0) == ()
    assert filter_blacklisted(["btc", "ETH", "", "sol"], ["eth", "xrp"]) == ("BTC", "SOL")


def test_followability_reconciliation_monitor_and_safe_mode() -> None:
    assert followability_score(liquidity_score=100, pattern_score=100) == 100.0
    assert followability_score(liquidity_score=0, pattern_score=0, latency_penalty=5) == 0.0
    assert followability_score(liquidity_score=50, pattern_score=50, latency_penalty=10) == 40.0
    assert reconcile_follow_signal(expected_coin="btc", observed_coin="BTC") == (True, "ok")
    assert reconcile_follow_signal(expected_coin="BTC", observed_coin="ETH") == (False, "coin_mismatch")

    monitor = build_monitor_output(status="RUNNING", wallets="3", signals=4.0, accepted=2, rejected=2, pnl_usdt=1.234567891)
    assert monitor["wallets"] == 3 and monitor["signals"] == 4
    assert monitor["pnl_usdt"] == 1.23456789
    assert monitor["paper_only"] is True and monitor["external_action"] is False
    assert build_monitor_output(status="IDLE", wallets=0, signals=0, accepted=0, rejected=0, pnl_usdt=None)["pnl_usdt"] == 0.0

    assert is_safe_mode_enabled()
    assert is_safe_mode_enabled("paper")
    assert not is_safe_mode_enabled("REAL_EXECUTION")
    assert not is_safe_mode_enabled("real_execution")


def test_wallet_degradation_boundary() -> None:
    assert wallet_degraded(-0.01)
    assert not wallet_degraded(0.0)
    assert wallet_degraded(4.9, min_recent_expectancy_bps=5.0)
    assert not wallet_degraded(5.0, min_recent_expectancy_bps=5.0)


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.limit_value = None

    def order_by(self, expression):
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def all(self):
        return self.rows[: self.limit_value]


class _Session:
    def __init__(self, rows):
        self.query_obj = _Query(rows)

    def query(self, model):
        return self.query_obj


def test_leaderboard_follow_shortlist_limit() -> None:
    rows = [type("Row", (), {"wallet_address": value})() for value in ("a", "b", "c")]
    session = _Session(rows)
    assert load_leaderboard_follow_shortlist(session, limit=2) == ["a", "b"]
    assert session.query_obj.limit_value == 2


def test_following_and_latency_wrappers_import() -> None:
    for name in (
        "hl_observer.following.copy_delay",
        "hl_observer.following.position_follower",
        "hl_observer.paper.latency_model",
    ):
        module = importlib.import_module(name)
        assert module.__name__ == name
