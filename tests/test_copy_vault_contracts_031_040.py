from __future__ import annotations

from hl_observer.collection.vault_fills_backfill import pagination_boundary_receipt
from hl_observer.copy_vault.ambiguous_action_deny import decision_with_pre_state
from hl_observer.copy_vault.exactly_once_source_fill import identity_stability_receipt
from hl_observer.copy_vault.fill_batching_window import stable_causal_order
from hl_observer.copy_vault.order_level_fill_aggregation import deduplicate_partial_fills
from hl_observer.copy_vault.reconnect_replay_suppression import deduplicate_reconnect_fills
from hl_observer.copy_vault.stream_cursor_persistence import atomic_cursor_fill_receipt
from hl_observer.copy_vault.vault_heartbeat import classify_connection_liveness
from hl_observer.copy_vault.ws_rest_disagreement_quarantine import reconciliation_receipt
from hl_observer.wallets.user_fills_live import classify_snapshot_fill_entry


def test_snapshot_never_becomes_a_new_entry() -> None:
    assert classify_snapshot_fill_entry(is_snapshot=True, fill_count=2)["accept_new_entry"] is False
    assert classify_snapshot_fill_entry(is_snapshot=False, fill_count=1)["accept_new_entry"] is True


def test_restart_identity_is_stable_across_ws_and_rest() -> None:
    fill = {"wallet": "0xabc", "tid": "t-1", "oid": "o-1"}
    receipt = identity_stability_receipt(fill, dict(fill))
    assert receipt["status"] == "PROVEN"
    assert receipt["same_identity"] is True


def test_partial_fills_with_distinct_tids_survive() -> None:
    result = deduplicate_partial_fills(
        [{"oid": "o", "tid": "t1"}, {"oid": "o", "tid": "t2"}, {"oid": "o", "tid": "t1"}]
    )
    assert result["retained_count"] == 2


def test_pagination_keeps_distinct_boundary_tids_at_same_millisecond() -> None:
    rows = [{"time": 1000, "tid": "t1", "coin": "BTC"}, {"time": 1000, "tid": "t2", "coin": "BTC"}]
    result = pagination_boundary_receipt([rows[:1], rows[1:] + [rows[0]]])
    assert result["status"] == "PROVEN"
    assert result["retained_count"] == 2


def test_connected_silence_is_distinguished_from_unconfirmed_subscription() -> None:
    assert classify_connection_liveness(heartbeat_seen=True, data_messages=0, subscription_ack=True)["state"] == "CONNECTED_NO_DATA"
    assert classify_connection_liveness(heartbeat_seen=True, data_messages=0, subscription_ack=False)["state"] == "SUBSCRIPTION_UNCONFIRMED"


def test_ws_rest_divergence_blocks_open() -> None:
    result = reconciliation_receipt(valeur_ws=10.0, valeur_rest=11.0)
    assert result["status"] == "PROVEN"
    assert result["open_allowed"] is False


def test_same_timestamp_burst_order_is_deterministic() -> None:
    first = [{"time": 1000, "tid": "b", "coin": "BTC"}, {"time": 1000, "tid": "a", "coin": "BTC"}]
    second = list(reversed(first))
    assert stable_causal_order(first)["fills"] == stable_causal_order(second)["fills"]


def test_cursor_fill_resume_requires_both_persisted() -> None:
    assert atomic_cursor_fill_receipt(
        fill_id="fill-1", cursor_before=1, cursor_after=2, fill_persisted=True, cursor_persisted=True
    )["resume_allowed"] is True
    assert atomic_cursor_fill_receipt(
        fill_id="fill-1", cursor_before=1, cursor_after=2, fill_persisted=True, cursor_persisted=False
    )["resume_allowed"] is False


def test_reconnect_keeps_new_tid_at_same_timestamp() -> None:
    result = deduplicate_reconnect_fills(
        [
            {"time": 1000, "tid": "t1", "coin": "BTC"},
            {"time": 1000, "tid": "t1", "coin": "BTC"},
            {"time": 1000, "tid": "t2", "coin": "BTC"},
        ]
    )
    assert result["retained_count"] == 2


def test_unknown_pre_state_cannot_become_open() -> None:
    result = decision_with_pre_state("OPEN", pre_state="UNKNOWN", confiance=1.0)
    assert result["status"] == "PROVEN"
    assert result["nouvelle_exposition"] is False
