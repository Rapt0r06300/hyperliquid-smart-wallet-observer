import math

from hl_observer.backtesting.lead_lag_reference_residual import compute_reference_residual


def _row(ts, price, source="aligned.jsonl"):
    return {"observable_at_ms": ts, "price": price, "source_id": source}


def test_reference_residual_ignores_future_rows_and_uses_only_causal_observations():
    reference = [_row(1_000, 100.0), _row(2_000, 101.0), _row(3_000, 500.0)]
    follower = [_row(1_000, 50.0), _row(2_000, 50.25), _row(3_000, 1.0)]

    result = compute_reference_residual(
        reference,
        follower,
        decision_ms=2_000,
        window_ms=1_000,
        beta=0.5,
        beta_asof_ms=900,
    )

    expected_ref = math.log(101.0 / 100.0) * 10_000.0
    expected_follower = math.log(50.25 / 50.0) * 10_000.0
    assert result["status"] == "OK"
    assert result["reference_return_bps"] == expected_ref
    assert result["follower_return_bps"] == expected_follower
    assert result["residual_bps"] == expected_follower - 0.5 * expected_ref
    assert result["max_observable_at_ms"] == 2_000
    assert result["heldout_loaded"] is False


def test_reference_residual_fails_closed_when_beta_was_not_known_before_window():
    rows = [_row(1_000, 100.0), _row(2_000, 101.0)]
    result = compute_reference_residual(
        rows,
        rows,
        decision_ms=2_000,
        window_ms=1_000,
        beta=1.0,
        beta_asof_ms=1_001,
    )
    assert result == {
        "status": "UNMEASURABLE",
        "reason": "BETA_NOT_CAUSAL",
        "decision_ms": 2_000,
        "window_ms": 1_000,
        "paper_read_only": True,
        "real_execution": False,
        "heldout_loaded": False,
    }


def test_reference_residual_fails_closed_without_common_aligned_source():
    reference = [_row(1_000, 100.0, "leader.jsonl"), _row(2_000, 101.0, "leader.jsonl")]
    follower = [_row(1_000, 50.0, "follower.jsonl"), _row(2_000, 50.5, "follower.jsonl")]
    result = compute_reference_residual(
        reference,
        follower,
        decision_ms=2_000,
        window_ms=1_000,
        beta=1.0,
        beta_asof_ms=900,
    )
    assert result["status"] == "UNMEASURABLE"
    assert result["reason"] == "NO_COMMON_ALIGNED_SOURCE"
