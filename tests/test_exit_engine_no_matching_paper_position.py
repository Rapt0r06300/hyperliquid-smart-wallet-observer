"""Phase 5: exit with no matching paper position -> NO_TRADE (deny-by-default)."""

from __future__ import annotations

from datetime import datetime, timezone

from hyper_smart_observer.paper_trading.exit_engine import (
    ExitAction,
    ExitTrigger,
    LeaderExitSignal,
    OpenPaperPosition,
    decide_leader_exit,
    decide_stop_exits,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _btc():
    return OpenPaperPosition(
        trade_id="t1", coin="BTC", side="BUY", entry_price=100.0, size=1.0,
        opened_at=T0, wallet_address="0x" + "a" * 40,
    )


def test_leader_close_no_matching_position_is_no_trade():
    sig = LeaderExitSignal(coin="ETH", trigger=ExitTrigger.LEADER_CLOSE, exit_reference_price=100.0)
    decisions = decide_leader_exit(sig, [_btc()])
    assert decisions[0].action == ExitAction.NO_TRADE
    assert "NO_MATCHING_PAPER_POSITION_FOR_CLOSE" in decisions[0].reason_codes


def test_stop_exit_no_matching_position_is_no_trade():
    decisions = decide_stop_exits([_btc()], coin="ETH", current_price=100.0, now=T0)
    assert decisions[0].action == ExitAction.NO_TRADE
    assert "NO_MATCHING_PAPER_POSITION_FOR_CLOSE" in decisions[0].reason_codes


def test_unpriceable_exit_is_no_trade():
    sig = LeaderExitSignal(coin="BTC", trigger=ExitTrigger.LEADER_CLOSE, exit_reference_price=0.0)
    decisions = decide_leader_exit(sig, [_btc()])
    assert decisions[0].action == ExitAction.NO_TRADE
