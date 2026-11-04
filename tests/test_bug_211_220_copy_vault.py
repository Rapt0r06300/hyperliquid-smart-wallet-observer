from hl_observer.backtesting.copy_vault_replay_controls import (
    checkpoint_boundary_receipt,
    checkpoint_dedup_receipt,
    dataset_pnl_stability_receipt,
    engine_parity_receipt,
    event_hash_collision_receipt,
    fee_config_freeze_receipt,
    liquidatable_exposure_receipt,
    refusal_reason_receipt,
    shard_order_preservation_receipt,
    thread_count_determinism_receipt,
)


def test_bug_211_fast_replay_matches_precise_engine():
    assert engine_parity_receipt(fast_engine_hash="x", precise_engine_hash="x", input_hash="i")["status"] == "PROVEN"
    assert engine_parity_receipt(fast_engine_hash="x", precise_engine_hash="y", input_hash="i")["status"] == "REJECTED"


def test_bug_212_replay_fee_config_is_frozen():
    assert fee_config_freeze_receipt(replay_config_hash="a", current_config_hash="a")["status"] == "PROVEN"
    assert fee_config_freeze_receipt(replay_config_hash="a", current_config_hash="b")["status"] == "REJECTED"


def test_bug_213_checkpoint_boundary_is_kept():
    assert checkpoint_boundary_receipt(boundary_event_included=True, next_event_is_after_boundary=True)["status"] == "PROVEN"
    assert checkpoint_boundary_receipt(boundary_event_included=False, next_event_is_after_boundary=True)["status"] == "REJECTED"


def test_bug_214_checkpoint_event_is_not_replayed():
    assert checkpoint_dedup_receipt(checkpoint_event_id="e1", replayed_event_ids=["e2"])["status"] == "PROVEN"
    assert checkpoint_dedup_receipt(checkpoint_event_id="e1", replayed_event_ids=["e1"])["status"] == "REJECTED"


def test_bug_215_frozen_dataset_pnl_is_stable():
    assert dataset_pnl_stability_receipt(input_hashes=["a", "a"], pnl_values=[1, 1])["status"] == "PROVEN"
    assert dataset_pnl_stability_receipt(input_hashes=["a", "a"], pnl_values=[1, 2])["status"] == "REJECTED"


def test_bug_216_event_hash_collision_is_rejected():
    assert event_hash_collision_receipt(event_hashes=["a", "b"], native_event_ids=["1", "2"])["status"] == "PROVEN"
    assert event_hash_collision_receipt(event_hashes=["a", "a"], native_event_ids=["1", "2"])["status"] == "REJECTED"


def test_bug_217_compression_preserves_shard_order():
    assert shard_order_preservation_receipt(source_event_ids=["1", "2"], decompressed_event_ids=["1", "2"])["status"] == "PROVEN"
    assert shard_order_preservation_receipt(source_event_ids=["1", "2"], decompressed_event_ids=["2", "1"])["status"] == "REJECTED"


def test_bug_218_thread_count_does_not_change_output():
    assert thread_count_determinism_receipt(outputs_by_thread_count={1: {"pnl": 1}, 4: {"pnl": 1}})["status"] == "PROVEN"
    assert thread_count_determinism_receipt(outputs_by_thread_count={1: {"pnl": 1}, 4: {"pnl": 2}})["status"] == "REJECTED"


def test_bug_219_refusal_reason_is_retained():
    assert refusal_reason_receipt([{"refused": True, "reason": "MISSING_SHARD"}])["status"] == "PROVEN"
    assert refusal_reason_receipt([{"refused": True, "reason": ""}])["status"] == "REJECTED"


def test_bug_220_final_exposure_is_liquidable():
    assert liquidatable_exposure_receipt(exposure_usd=5, available_exit_liquidity_usd=6, observed_book=True)["status"] == "PROVEN"
    assert liquidatable_exposure_receipt(exposure_usd=7, available_exit_liquidity_usd=6, observed_book=True)["status"] == "REJECTED"
