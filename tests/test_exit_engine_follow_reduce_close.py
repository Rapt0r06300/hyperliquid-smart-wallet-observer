"""Phase 5: exit engine follows leader reduce/close via the existing PaperEngine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.hyperliquid_client.models import ScoreBreakdown, Wallet, WalletScoreStatus
from hyper_smart_observer.paper_trading.exit_engine import (
    ExitAction,
    ExitPolicy,
    ExitTrigger,
    LeaderExitSignal,
    OpenPaperPosition,
    apply_exit_decisions,
    decide_leader_exit,
    decide_stop_exits,
)
from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from hyper_smart_observer.storage.database import get_connection, initialize_database
from hyper_smart_observer.storage.repositories import scores_repo
from hyper_smart_observer.storage.repositories.wallet_repo import insert_wallet

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _pos(trade_id, *, side="BUY", entry=100.0, size=1.0, age_min=0, coin="BTC"):
    return OpenPaperPosition(
        trade_id=trade_id, coin=coin, side=side, entry_price=entry, size=size,
        opened_at=T0 + timedelta(minutes=age_min), wallet_address="0x" + "a" * 40,
    )


def test_leader_reduce_closes_single_oldest_paper_trade():
    positions = [_pos("t-old", age_min=0), _pos("t-new", age_min=5)]
    sig = LeaderExitSignal(
        coin="BTC", trigger=ExitTrigger.LEADER_REDUCE, exit_reference_price=110.0,
        leader_prev_size=4.0, leader_curr_size=2.0,
    )
    decisions = decide_leader_exit(sig, positions)
    assert len(decisions) == 1
    assert decisions[0].action == ExitAction.REDUCE
    assert decisions[0].trade_id == "t-old"
    assert decisions[0].reduce_fraction == 0.5


def test_leader_reduce_fraction_tracks_leader_size_drop():
    sig = LeaderExitSignal(
        coin="BTC", trigger=ExitTrigger.LEADER_REDUCE, exit_reference_price=110.0,
        leader_prev_size=4.0, leader_curr_size=3.0,
    )
    decisions = decide_leader_exit(sig, [_pos("t1")])
    assert decisions[0].action == ExitAction.REDUCE
    assert decisions[0].reduce_fraction == 0.25


def test_leader_close_closes_all_matching_paper_trades():
    positions = [_pos("t1", age_min=0), _pos("t2", age_min=5), _pos("eth", coin="ETH")]
    sig = LeaderExitSignal(coin="BTC", trigger=ExitTrigger.LEADER_CLOSE, exit_reference_price=110.0)
    decisions = decide_leader_exit(sig, positions)
    assert {d.trade_id for d in decisions} == {"t1", "t2"}
    assert all(d.action == ExitAction.CLOSE for d in decisions)


def test_leader_reduce_rejected_when_size_did_not_decrease():
    sig = LeaderExitSignal(
        coin="BTC", trigger=ExitTrigger.LEADER_REDUCE, exit_reference_price=110.0,
        leader_prev_size=2.0, leader_curr_size=3.0,
    )
    decisions = decide_leader_exit(sig, [_pos("t1")])
    assert decisions[0].action == ExitAction.NO_TRADE
    assert "REDUCE_OR_CLOSE_NOT_ENTRY" in decisions[0].reason_codes


def test_stop_exits_trigger_max_holding_and_max_adverse():
    long_old = _pos("hold", side="BUY", entry=100.0, age_min=0)
    long_loss = _pos("mae", side="BUY", entry=100.0, age_min=0)
    now = T0 + timedelta(hours=2)  # > 1h max holding for "hold"
    d_hold = decide_stop_exits([long_old], coin="BTC", current_price=101.0, now=now,
                               policy=ExitPolicy(max_holding_seconds=3600))
    assert d_hold[0].trigger == ExitTrigger.MAX_HOLDING
    # adverse: long entered 100, price 99 = -100 bps <= -25 bps
    d_mae = decide_stop_exits([long_loss], coin="BTC", current_price=99.0, now=T0,
                              policy=ExitPolicy(max_adverse_bps=25))
    assert d_mae[0].trigger == ExitTrigger.MAX_ADVERSE


def _config(tmp_path):
    return AppConfig(database_path=tmp_path / "paper.sqlite3")


def _store_score(config, wallet):
    initialize_database(config)
    with get_connection(config) as conn:
        insert_wallet(conn, Wallet(address=wallet, source="test"))
        scores_repo.insert_score_breakdown(
            conn,
            ScoreBreakdown(
                wallet_address=wallet, calculated_at=T0, status=WalletScoreStatus.SCORED,
                total_fills=50, usable_fills=50, skipped_fills=0,
                sample_quality_score=90.0, confidence_score=90.0, risk_score=90.0,
                profit_factor=2.0, net_pnl=10.0, final_score=80.0,
            ),
        )
        conn.commit()


def _positions_from_open(sim):
    out = []
    for row in sim.list_open_trades():
        out.append(
            OpenPaperPosition(
                trade_id=row["trade_id"], coin=row["coin"], side=row["side"],
                entry_price=float(row["entry_price"]), size=float(row["size"]),
                opened_at=datetime.fromisoformat(row["opened_at"]),
                wallet_address=row["wallet_address"],
            )
        )
    return out


def test_integration_reduce_then_close_via_existing_simulator(tmp_path):
    config = _config(tmp_path)
    wallet = "0x" + "a" * 40
    _store_score(config, wallet)
    sim = PaperTradingSimulator(config)
    for _ in range(2):
        intent = sim.create_intent_from_wallet_score(
            wallet_address=wallet, coin="BTC", side="BUY",
            reference_price=100.0, requested_notional=50.0,
        )
        assert sim.open_paper_trade(intent).success
    assert len(sim.list_open_trades()) == 2

    # Follow leader REDUCE -> oldest paper trade is partially closed, not abandoned.
    reduce_sig = LeaderExitSignal(
        coin="BTC", trigger=ExitTrigger.LEADER_REDUCE, exit_reference_price=110.0,
        leader_prev_size=4.0, leader_curr_size=2.0,
    )
    res = apply_exit_decisions(sim, decide_leader_exit(reduce_sig, _positions_from_open(sim)))
    assert len(res) == 1 and res[0].success
    assert res[0].net_pnl is not None and res[0].net_pnl > 0  # long, +10% move
    assert res[0].realized_trade_id != res[0].trade_id
    assert res[0].remaining_size is not None and res[0].remaining_size > 0
    assert len(sim.list_open_trades()) == 2

    # Follow leader CLOSE -> all remaining open paper exposure is closed.
    close_sig = LeaderExitSignal(coin="BTC", trigger=ExitTrigger.LEADER_CLOSE, exit_reference_price=110.0)
    res2 = apply_exit_decisions(sim, decide_leader_exit(close_sig, _positions_from_open(sim)))
    assert len(res2) == 2 and all(item.success for item in res2)
    assert len(sim.list_open_trades()) == 0
