from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.analysis.trade_lifecycle import (  # noqa: E402
    aggregate_partial_fills,
    close_paper_gate,
    cycle_event_admission,
    pre_entry_score,
    rankable_trade_observations,
    reconcile_fill_position,
    robust_leader_score,
    wallet_activity_gate,
)
from hl_observer.wallets.snapshot_engine import SnapshotData, SnapshotEngine  # noqa: E402


WALLET = "0x" + "2" * 40


def test_bug131_one_large_gain_cannot_dominate_robust_score() -> None:
    result = robust_leader_score([1.0, 1.0, 1.0, 1_000.0], trim_fraction=0.2)
    assert result["status"] == "PROVEN"
    assert result["score"] == 1.0


def test_bug132_post_entry_pnl_is_excluded_from_score_inputs() -> None:
    result = pre_entry_score(
        [{"timestamp_ms": 99, "pnl_usdc": 2}, {"timestamp_ms": 101, "pnl_usdc": 999}],
        entry_ts_ms=100,
    )
    assert result["values"] == [2.0]
    assert result["excluded_post_entry"] is True


def test_bug133_inactive_wallet_loses_active_gate() -> None:
    assert wallet_activity_gate(last_seen_ms=1, now_ms=10_000, max_age_ms=100)["active"] is False


def test_bug134_close_without_paper_position_is_not_eligible() -> None:
    result = close_paper_gate(has_paper_position=False, native_trade_id="close-1")
    assert result["paper_eligible"] is False


def test_bug135_partial_quantities_are_preserved_and_aggregated() -> None:
    result = aggregate_partial_fills(
        [{"oid": "o1", "sz": "0.4", "px": "100"}, {"oid": "o1", "sz": "0.6", "px": "110"}]
    )
    assert result["status"] == "PROVEN"
    assert result["groups"]["o1"]["quantity"] == 1.0
    assert result["groups"]["o1"]["vwap"] == 106.0


def test_bug136_vwap_is_not_an_unweighted_price_mean() -> None:
    result = aggregate_partial_fills(
        [{"tid": "t1", "sz": "9", "px": "100"}, {"tid": "t1", "sz": "1", "px": "200"}]
    )
    assert result["groups"]["t1"]["vwap"] == 110.0


def test_bug137_fill_position_mismatch_is_not_proven() -> None:
    result = reconcile_fill_position(previous_size=1, fills_delta=0.5, observed_size=2)
    assert result["status"] == "PROVEN"
    assert result["reconciled"] is False


def test_bug138_mid_without_fill_price_cannot_be_paper_eligible() -> None:
    previous = SnapshotData(wallet_address=WALLET, local_received_ts=1, exchange_ts=1)
    current = SnapshotData(
        wallet_address=WALLET,
        local_received_ts=2,
        exchange_ts=2,
        positions=[{"coin": "BTC", "szi": "1"}],
        fills=[{"coin": "BTC", "side": "B", "sz": "1", "time": 2}],
        all_mids={"BTC": "100"},
    )
    delta = SnapshotEngine().compare_snapshots(current, previous).deltas[0]
    assert delta.proofs["price_from_fill"] is False
    assert delta.is_paper_eligible is False


def test_bug139_withdrawals_are_excluded_from_leader_ranking_inputs() -> None:
    rows = rankable_trade_observations(
        [{"event_kind": "withdrawal", "id": "w1"}, {"event_kind": "fill", "tid": "t1"}]
    )
    assert rows == [{"event_kind": "fill", "tid": "t1"}]


def test_bug140_stale_cycle_and_epoch_are_rejected() -> None:
    assert cycle_event_admission(event_cycle="old", current_cycle="new")["admitted"] is False
    assert cycle_event_admission(event_cycle="c", current_cycle="c", phase_epoch=1, current_phase_epoch=2)["admitted"] is False
    previous = SnapshotData(wallet_address=WALLET, local_received_ts=1, cycle_id="c1")
    current = SnapshotData(wallet_address=WALLET, local_received_ts=2, cycle_id="c2")
    result = SnapshotEngine().compare_snapshots(current, previous)
    assert result.refusal_reason == "STALE_CYCLE"
