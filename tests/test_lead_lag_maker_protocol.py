from __future__ import annotations

from hl_observer.backtesting import lead_lag_queue_replay as module


DAY_MS = 86_400_000


def test_maker_protocol_signature_is_static_and_distinct_from_legacy_taker() -> None:
    signature = module.maker_protocol_signature()

    assert signature["calibration_protocol"] == (
        "lead_lag_queue_maker_walk_forward_v1"
    )
    assert signature["execution_model"] == (
        "causal_eth_strong_shock_full_fifo_maker_entry_taker_exit_v1"
    )
    assert signature["queue_rule"] == (
        "FIFO_PUBLIC_TRADES_CONSUME_AHEAD_PLUS_COMPLETE_OWN_QUANTITY"
    )
    assert signature["post_freeze_proof_policy"] == (
        "FIRST_TWO_COMPLETE_UTC_DAYS_AFTER_FREEZE_V1"
    )
    assert signature["minimum_complete_proof_days"] == 2
    assert "applied_latency_ms" not in signature


def test_post_freeze_proof_window_uses_only_complete_utc_days() -> None:
    frozen_at_ms = 10 * DAY_MS + 12_345
    evaluated_at_ms = 13 * DAY_MS + 99

    window = module.post_freeze_proof_window(
        frozen_at_ms=frozen_at_ms,
        evaluated_at_ms=evaluated_at_ms,
    )

    assert window["proof_start_ms"] == 11 * DAY_MS
    assert window["completed_cutoff_exclusive_ms"] == 13 * DAY_MS
    assert window["complete_days_available"] == 2
    assert window["segments"] == {
        "oos": (11 * DAY_MS, 12 * DAY_MS - 1),
        "forward": (12 * DAY_MS, 13 * DAY_MS - 1),
    }


def test_post_freeze_proof_window_is_empty_before_a_complete_day_exists() -> None:
    frozen_at_ms = 10 * DAY_MS + 12_345

    window = module.post_freeze_proof_window(
        frozen_at_ms=frozen_at_ms,
        evaluated_at_ms=11 * DAY_MS + 99,
    )

    assert window["complete_days_available"] == 0
    assert window["segments"] == {"oos": (None, None), "forward": (None, None)}
