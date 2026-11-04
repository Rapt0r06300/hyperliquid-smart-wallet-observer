from hl_observer.backtesting.copy_vault_replay_controls import (
    complete_segment_receipt,
    complete_shard_set_receipt,
    decision_data_causality_receipt,
    filesystem_order_receipt,
    future_book_access_receipt,
    negotiable_tick_receipt,
    publication_epoch_receipt,
    python_hash_seed_receipt,
    reconstructed_bbo_receipt,
    utc_timezone_receipt,
)


def test_bug_201_filesystem_order_is_explicit():
    assert filesystem_order_receipt(["a", "b"])["status"] == "PROVEN"
    assert filesystem_order_receipt(["b", "a"])["status"] == "REJECTED"


def test_bug_202_python_hash_seed_is_pinned():
    assert python_hash_seed_receipt(hash_seed=7, hash_randomization_disabled=True)["status"] == "PROVEN"
    assert python_hash_seed_receipt(hash_seed=None, hash_randomization_disabled=False)["status"] == "REJECTED"


def test_bug_203_replay_uses_utc():
    assert utc_timezone_receipt(timezone_name="UTC", timestamps_utc=True)["status"] == "PROVEN"
    assert utc_timezone_receipt(timezone_name="Europe/Paris", timestamps_utc=False)["status"] == "REJECTED"


def test_bug_204_future_data_cannot_influence_decision():
    assert decision_data_causality_receipt(data_ts_ms=10, decision_ts_ms=20, observed_before_decision=True)["status"] == "PROVEN"
    assert decision_data_causality_receipt(data_ts_ms=30, decision_ts_ms=20, observed_before_decision=False)["status"] == "REJECTED"


def test_bug_205_missing_shard_is_rejected():
    assert complete_shard_set_receipt(required_shards=["a", "b"], present_shards=["a", "b"])["status"] == "PROVEN"
    assert complete_shard_set_receipt(required_shards=["a", "b"], present_shards=["a"])["status"] == "REJECTED"


def test_bug_206_publication_epochs_cannot_mix():
    rows = [{"publication_epoch": 3}, {"publication_epoch": 3}]
    assert publication_epoch_receipt(rows, expected_epoch=3)["status"] == "PROVEN"
    assert publication_epoch_receipt(rows + [{"publication_epoch": 4}], expected_epoch=3)["status"] == "REJECTED"


def test_bug_207_partial_segment_is_rejected():
    assert complete_segment_receipt(segment_complete=True, partial_explicit=False)["status"] == "PROVEN"
    assert complete_segment_receipt(segment_complete=False, partial_explicit=True)["status"] == "REJECTED"


def test_bug_208_bbo_requires_reconstructed_levels():
    assert reconstructed_bbo_receipt(bid=99, ask=101, source_level_count=2, reconstructed=True)["status"] == "PROVEN"
    assert reconstructed_bbo_receipt(bid=99, ask=101, source_level_count=0, reconstructed=False)["status"] == "REJECTED"


def test_bug_209_non_negotiable_tick_is_rejected():
    assert negotiable_tick_receipt(price=100, tick_size=0.5, tradeable=True)["status"] == "PROVEN"
    assert negotiable_tick_receipt(price=100.1, tick_size=0.5, tradeable=False)["status"] == "REJECTED"


def test_bug_210_future_book_is_rejected():
    assert future_book_access_receipt(book_ts_ms=10, visible_ts_ms=15, decision_ts_ms=20)["status"] == "PROVEN"
    assert future_book_access_receipt(book_ts_ms=21, visible_ts_ms=21, decision_ts_ms=20)["status"] == "REJECTED"
