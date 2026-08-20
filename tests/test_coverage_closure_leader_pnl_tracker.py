from __future__ import annotations

import math

from hl_observer.copying.leader_pnl_tracker import (
    LeaderPerformance,
    LeaderPnLTracker,
    LeaderTradeRecord,
)


def _trade(
    leader: str,
    *,
    pnl: float,
    pnl_bps: float | None = None,
    hold_ms: int = 100,
    signal_age_ms: int = 20,
    exit_ts: float = 2.0,
) -> LeaderTradeRecord:
    return LeaderTradeRecord(
        leader_address=leader,
        coin="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=101.0 if pnl > 0 else 99.0,
        notional_usdt=50.0,
        pnl_usdt=pnl,
        pnl_bps=float(pnl_bps if pnl_bps is not None else pnl * 10.0),
        entry_timestamp=1.0,
        exit_timestamp=exit_ts,
        hold_duration_ms=hold_ms,
        signal_age_at_entry_ms=signal_age_ms,
    )


def test_performance_derived_metrics_and_all_statuses() -> None:
    perf = LeaderPerformance(leader_address="0x0")
    assert perf.win_rate == 0.0
    assert perf.avg_pnl_per_trade_usdt == 0.0
    assert perf.avg_pnl_per_trade_bps == 0.0
    assert perf.profit_factor == 0.0
    assert perf.status == "EVALUATING"

    perf.total_trades = 3
    perf.winning_trades = 2
    perf.total_pnl_usdt = 5.0
    perf.total_pnl_bps = 30.0
    assert perf.win_rate == 2 / 3
    assert perf.avg_pnl_per_trade_usdt == 5 / 3
    assert perf.avg_pnl_per_trade_bps == 10.0
    assert math.isinf(perf.profit_factor)
    assert perf.status == "PROFITABLE"

    perf.max_single_win_usdt = 4.0
    perf.max_single_loss_usdt = -2.0
    assert perf.profit_factor == 2.0

    perf.total_pnl_usdt = -1.0
    perf.winning_trades = 1
    perf.consecutive_losses = 4
    assert perf.status == "EJECT_STREAK"

    perf.consecutive_losses = 0
    perf.total_trades = 5
    perf.winning_trades = 2
    assert perf.status == "EJECT_NEGATIVE_PNL"

    perf.total_pnl_usdt = 1.0
    perf.winning_trades = 1
    assert perf.status == "EJECT_LOW_WIN_RATE"

    perf.winning_trades = 2
    assert perf.status == "MARGINAL"


def test_record_trade_updates_wins_losses_averages_and_lookup() -> None:
    tracker = LeaderPnLTracker()
    first = tracker.record_trade(
        _trade("0xABC", pnl=3.0, pnl_bps=30.0, hold_ms=100, signal_age_ms=20, exit_ts=2.0)
    )
    assert first.leader_address == "0xabc"
    assert first.total_trades == 1
    assert first.winning_trades == 1
    assert first.consecutive_losses == 0
    assert first.max_single_win_usdt == 3.0
    assert first.avg_hold_duration_ms == 100.0
    assert first.avg_signal_age_ms == 20.0
    assert first.last_trade_timestamp == 2.0

    second = tracker.record_trade(
        _trade("0xabc", pnl=-2.0, pnl_bps=-20.0, hold_ms=300, signal_age_ms=60, exit_ts=3.0)
    )
    assert second.total_trades == 2
    assert second.winning_trades == 1
    assert second.losing_trades == 1
    assert second.total_pnl_usdt == 1.0
    assert second.total_pnl_bps == 10.0
    assert second.consecutive_losses == 1
    assert second.max_single_loss_usdt == -2.0
    assert second.avg_hold_duration_ms == 200.0
    assert second.avg_signal_age_ms == 40.0
    assert tracker.get_leader_performance("0xABC") is second
    assert tracker.get_leader_performance("missing") is None


def test_should_eject_all_decision_paths() -> None:
    tracker = LeaderPnLTracker()
    assert tracker.should_eject_leader("missing") == (False, "no_data")

    tracker.record_trade(_trade("eval", pnl=-1.0))
    assert tracker.should_eject_leader("EVAL") == (False, "evaluating")

    for _ in range(4):
        tracker.record_trade(_trade("streak", pnl=-1.0))
    eject, reason = tracker.should_eject_leader("STREAK")
    assert eject is True and reason == "consecutive_losses_4"

    for pnl in (-1.0, 1.0, -1.0, 1.0, -2.0):
        tracker.record_trade(_trade("negative", pnl=pnl))
    eject, reason = tracker.should_eject_leader("negative")
    assert eject is True and reason == "negative_pnl_after_5_trades"

    for pnl in (1.0, -1.0, -1.0, 1.0, 1.0, -1.0):
        tracker.record_trade(_trade("low", pnl=pnl))
    low = tracker.get_leader_performance("low")
    assert low is not None
    low.total_pnl_usdt = 1.0
    low.winning_trades = 1
    low.losing_trades = 5
    low.consecutive_losses = 0
    eject, reason = tracker.should_eject_leader("low")
    assert eject is True and reason.startswith("low_win_rate_")

    for pnl in (1.0, -0.2, 1.0):
        tracker.record_trade(_trade("ok", pnl=pnl))
    assert tracker.should_eject_leader("ok") == (False, "ok")


def test_profitable_sort_eject_list_and_session_summary() -> None:
    empty = LeaderPnLTracker()
    assert empty.get_all_performances() == []
    assert empty.get_profitable_leaders() == []
    assert empty.get_leaders_to_eject() == []
    assert empty.get_session_summary() == {
        "total_leaders_tracked": 0,
        "profitable_leaders": 0,
        "losing_leaders": 0,
        "total_session_pnl_usdt": 0,
        "total_trades": 0,
        "overall_win_rate": 0.0,
        "best_leader": None,
        "best_leader_pnl": 0.0,
        "worst_leader": None,
        "worst_leader_pnl": 0.0,
        "leaders_to_eject": 0,
    }

    tracker = LeaderPnLTracker()
    for pnl in (2.0, 1.0, -0.2):
        tracker.record_trade(_trade("winner", pnl=pnl))
    for _ in range(4):
        tracker.record_trade(_trade("loser", pnl=-1.0))

    perfs = tracker.get_all_performances()
    assert [p.leader_address for p in perfs] == ["winner", "loser"]
    assert tracker.get_profitable_leaders() == ["winner"]
    ejects = tracker.get_leaders_to_eject()
    assert ejects == [("loser", "consecutive_losses_4")]

    summary = tracker.get_session_summary()
    assert summary["total_leaders_tracked"] == 2
    assert summary["profitable_leaders"] == 1
    assert summary["losing_leaders"] == 1
    assert summary["total_trades"] == 7
    assert summary["best_leader"] == "winner"
    assert summary["worst_leader"] == "loser"
    assert summary["leaders_to_eject"] == 1
    assert 0.0 < summary["overall_win_rate"] < 1.0
