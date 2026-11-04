from __future__ import annotations

from hl_observer.backtesting.backtest_live_parity import paper_replay_parity_receipt
from hl_observer.backtesting.copy_vault_book_loader import future_book_access_receipt
from hl_observer.backtesting.copy_vault_causal_selection import stable_event_order_receipt
from hl_observer.backtesting.copy_vault_protocol import same_timestamp_direction_receipt
from hl_observer.backtesting.replay_doctor import no_trade_classification_receipt
from hl_observer.backtesting.replay_engine import replay_determinism_receipt
from hl_observer.backtesting.vectorized import vectorized_parity_receipt
from hl_observer.datasets.streaming_materializer import streaming_codec_receipt
from hl_observer.research.reproducibility import environment_freeze_receipt


def test_141_replay_is_stable_under_input_permutation() -> None:
    rows = [
        {"event_id": "b", "ts_ms": 1_000},
        {"event_id": "a", "ts_ms": 1_000},
    ]
    receipt = replay_determinism_receipt(rows, delay_seconds=1.0)
    assert receipt["status"] == "PROVEN"
    assert receipt["event_ids"] == ("a", "b")


def test_142_paper_and_replay_signal_parity_is_strict() -> None:
    rows = [{"signal_id": "s1", "decision": "COPY", "reason": "eligible"}]
    receipt = paper_replay_parity_receipt(rows, list(rows))
    assert receipt["verdict"] == "PROVEN"
    assert receipt["compared"] == 1


def test_143_equal_timestamp_events_have_native_tie_break() -> None:
    receipt = stable_event_order_receipt([
        {"event_id": "z", "ts_ms": 100},
        {"event_id": "a", "ts_ms": 100},
    ])
    assert receipt["status"] == "PROVEN"
    assert receipt["ordered_event_ids"] == ("a", "z")


def test_144_equal_timestamp_opposite_fills_keep_both_directions() -> None:
    receipt = same_timestamp_direction_receipt([
        {"event_id": "sell", "ts_ms": 100, "direction": "SELL"},
        {"event_id": "buy", "ts_ms": 100, "direction": "BUY"},
    ])
    assert receipt["status"] == "PROVEN"
    assert receipt["opposing_directions_preserved"] is True


def test_145_missing_replay_inputs_are_not_zero_trade_performance() -> None:
    receipt = no_trade_classification_receipt([], [])
    assert receipt["status"] == "UNMEASURABLE"
    assert receipt["zero_trade_is_not_performance"] is True


def test_146_future_book_snapshot_is_rejected() -> None:
    receipt = future_book_access_receipt(
        {
            "ts_ms": 2_000,
            "bid": 100.0,
            "ask": 101.0,
            "bids5": [{"px": 100.0, "sz": 1.0}],
            "asks5": [{"px": 101.0, "sz": 1.0}],
        },
        as_of_ms=1_000,
    )
    assert receipt["verdict"] == "REJECTED"
    assert receipt["future_snapshot_never_admitted"] is True


def test_147_vectorized_and_cpu_paths_have_equal_trade_hash() -> None:
    receipt = vectorized_parity_receipt(
        [100.0, 102.0], [101.0, 101.0], [1, -1], notional=100.0, cost_bps=2.0,
    )
    assert receipt["status"] == "PROVEN"
    assert receipt["trade_hash_reference"] == receipt["trade_hash_optimized"]


def test_148_streaming_codecs_preserve_order_contract() -> None:
    receipt = streaming_codec_receipt(
        [{"sequence": 0}, {"sequence": 1}], codec="gzip",
    )
    assert receipt["status"] == "PROVEN"
    assert receipt["sequence"] == (0, 1)


def test_149_environment_freeze_records_a_dependency_hash() -> None:
    receipt = environment_freeze_receipt(packages=())
    assert receipt["status"] == "PROVEN"
    assert len(receipt["dependency_hash"]) == 64


def test_150_environment_divergence_is_fail_closed() -> None:
    receipt = environment_freeze_receipt(
        packages=(), expected_versions={"missing-package": "0"},
    )
    assert receipt["status"] == "REJECTED"
    assert receipt["reason"] == "DEPENDENCY_VERSION_DIVERGENCE"
