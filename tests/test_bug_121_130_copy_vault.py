from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.analysis.trade_lifecycle import classify_trade_lifecycle  # noqa: E402
from hl_observer.wallet_universe.wallet_universe import wallet_identity_receipt  # noqa: E402
from hl_observer.wallets.position_delta_engine import (  # noqa: E402
    PositionAction,
    build_position_delta_from_fill,
    classify_same_timestamp_transitions,
    deduplicate_trade_fills,
)
from hl_observer.wallets.snapshot_engine import SnapshotData, SnapshotEngine  # noqa: E402


WALLET = "0x" + "1" * 40


def _fill(*, tid: str, side: str, size: str = "1", ts: int = 100) -> dict[str, object]:
    return {"tid": tid, "coin": "BTC", "time": ts, "side": side, "px": "100", "sz": size}


def test_bug121_duplicate_native_trade_cannot_duplicate_opening() -> None:
    rows = deduplicate_trade_fills([_fill(tid="t1", side="B"), _fill(tid="t1", side="B")])
    assert [row["tid"] for row in rows] == ["t1"]


def test_bug122_known_position_add_is_not_new_open() -> None:
    delta = build_position_delta_from_fill(WALLET, _fill(tid="t2", side="B", size="0.5"), previous_size=1.0)
    assert delta.action == PositionAction.ADD
    assert delta.new_size == 1.5


def test_bug123_same_side_reduction_is_not_inverse_position() -> None:
    delta = build_position_delta_from_fill(WALLET, _fill(tid="t3", side="A", size="0.5"), previous_size=1.0)
    assert delta.action == PositionAction.REDUCE
    assert delta.new_size == 0.5


def test_bug124_same_timestamp_close_then_open_is_deterministic() -> None:
    records = classify_same_timestamp_transitions(
        1.0,
        [_fill(tid="1", side="A"), _fill(tid="2", side="B")],
    )
    assert [record.action for record in records] == [PositionAction.CLOSE, PositionAction.OPEN]


def test_bug125_unknown_initial_position_is_not_assumed_flat() -> None:
    delta = build_position_delta_from_fill(WALLET, _fill(tid="t5", side="B"))
    assert delta.action == PositionAction.UNKNOWN
    assert delta.is_paper_eligible is False
    assert "initial_position_unknown" in delta.notes


def test_bug126_incomplete_fill_with_known_position_is_fail_closed() -> None:
    fill = {"tid": "t6", "coin": "BTC", "time": 100, "side": "B", "px": "100"}
    delta = build_position_delta_from_fill(WALLET, fill, previous_size=1.0)
    assert delta.action == PositionAction.UNKNOWN
    assert delta.is_paper_eligible is False


def test_bug127_cancelled_order_is_not_a_completed_fill() -> None:
    previous = SnapshotData(
        wallet_address=WALLET,
        local_received_ts=1,
        exchange_ts=1,
        positions=[{"coin": "BTC", "szi": "1"}],
    )
    current = SnapshotData(
        wallet_address=WALLET,
        local_received_ts=2,
        exchange_ts=2,
        positions=[{"coin": "BTC", "szi": "1"}],
        fills=[{"coin": "BTC", "event": "cancel", "side": "A", "sz": "1", "px": "100", "time": 2}],
    )
    assert SnapshotEngine().compare_snapshots(current, previous).deltas == []


def test_bug128_non_copy_vault_snapshot_scope_is_refused() -> None:
    previous = SnapshotData(wallet_address=WALLET, local_received_ts=1, scope="other")
    current = SnapshotData(wallet_address=WALLET, local_received_ts=2)
    result = SnapshotEngine().compare_snapshots(current, previous)
    assert result.refused is True
    assert result.refusal_reason == "ECONOMIC_SCOPE_NOT_COPY_VAULT"


def test_bug129_same_wallet_with_different_source_identity_is_refused() -> None:
    previous = SnapshotData(wallet_address=WALLET, local_received_ts=1, source_identity="source-a")
    current = SnapshotData(wallet_address=WALLET, local_received_ts=2, source_identity="source-b")
    result = SnapshotEngine().compare_snapshots(current, previous)
    assert result.refused is True
    assert result.refusal_reason == "SOURCE_IDENTITY_MISMATCH"


def test_bug130_proxy_link_requires_real_proof_hash() -> None:
    missing = wallet_identity_receipt(
        wallet_address=WALLET, native_identity="proxy-1", source="SAFE", proof_sha256=None
    )
    proven = wallet_identity_receipt(
        wallet_address=WALLET,
        native_identity="proxy-1",
        source="SAFE",
        proof_sha256="a" * 64,
    )
    assert missing.status == "UNMEASURABLE"
    assert proven.status == "PROVEN"


def test_trade_lifecycle_refuses_unproven_identity_or_order_event() -> None:
    order = classify_trade_lifecycle(
        wallet_address=WALLET,
        coin="BTC",
        action="CANCEL",
        native_trade_id="t-order",
        source="user_fills",
        wallet_identity_proven=True,
        confidence_score=1.0,
    )
    unknown = classify_trade_lifecycle(
        wallet_address=WALLET,
        coin="BTC",
        action="OPEN",
        native_trade_id="t-open",
        source="user_fills",
        wallet_identity_proven=False,
        confidence_score=1.0,
    )
    assert order.paper_eligible is False and order.refusal_reason == "NON_TRADE_EVENT"
    assert unknown.paper_eligible is False and unknown.refusal_reason == "WALLET_IDENTITY_UNPROVEN"
