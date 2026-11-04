from __future__ import annotations

from hl_observer.research.wallet_info_ratio import compare_markout_to_pnl_score


def _row(ts: int, episode: str, markout: float, pnl_score: float, outcome: float) -> dict:
    return {
        "signal_ts_ms": ts,
        "episode_id": episode,
        "leader_markout_score_bps": markout,
        "pnl_score_bps": pnl_score,
        "realized_net_pnl_bps": outcome,
    }


def test_markout_and_pnl_score_are_frozen_on_train_and_compared_on_same_oos() -> None:
    train = [
        _row(100, "tr-1", 10.0, 1.0, 0.0),
        _row(110, "tr-2", 20.0, 2.0, 0.0),
        _row(120, "tr-3", 30.0, 3.0, 0.0),
        _row(130, "tr-4", 40.0, 4.0, 0.0),
    ]
    oos = [
        _row(2_000, "oos-1", 5.0, 1.0, 1.0),
        _row(2_010, "oos-2", 15.0, 2.0, 2.0),
        _row(2_020, "oos-3", 35.0, 3.0, 5.0),
        _row(2_030, "oos-4", 45.0, 4.0, 6.0),
    ]

    result = compare_markout_to_pnl_score(train, oos, cutoff_ms=1_000, min_rows_per_bucket=2)

    assert result["status"] == "COMPARABLE"
    assert result["markout_predictor"]["threshold_train"] == 25.0
    assert result["markout_predictor"]["high"]["mean_outcome_bps"] == 5.5
    assert result["markout_predictor"]["low"]["mean_outcome_bps"] == 1.5
    assert result["same_oos_outcome"] is True
    assert result["prior_profitability_not_causal_claim"] is True


def test_markout_pnl_comparison_rejects_future_train_or_small_buckets() -> None:
    assert compare_markout_to_pnl_score(
        [_row(2_000, "future", 10.0, 1.0, 1.0)],
        [_row(3_000, "oos", 20.0, 2.0, 2.0)],
        cutoff_ms=1_000,
    )["status"] == "UNMEASURABLE"

    train = [_row(100 + i, f"tr-{i}", float(i), float(i), 0.0) for i in range(4)]
    oos = [_row(2_000 + i, f"oos-{i}", 10.0 + i, 10.0 + i, 1.0) for i in range(4)]
    result = compare_markout_to_pnl_score(train, oos, cutoff_ms=1_000, min_rows_per_bucket=3)
    assert result["status"] == "UNMEASURABLE"
    assert result["reason"] == "INSUFFICIENT_OOS_BUCKET_SAMPLE"
