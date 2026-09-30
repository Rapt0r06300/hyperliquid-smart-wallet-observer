from __future__ import annotations

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.realtime.recovery_engine import (
    RealtimeRecoveryEngine,
    ReconnectPolicy,
    RecoveryAction,
    StreamEventType,
    WatchStreamEvent,
    format_recovery_decision,
)


WALLET = "0x" + "1" * 40


def _engine() -> RealtimeRecoveryEngine:
    return RealtimeRecoveryEngine(
        ReconnectPolicy(
            stale_after_ms=5_000,
            max_event_gap_ms=5_000,
            max_sequence_gap=1,
            backfill_overlap_ms=250,
            max_backfill_window_ms=60_000,
            max_pages=2,
        )
    )


def _event(
    event_id: str,
    observed_at_ms: int,
    received_at_ms: int,
    *,
    sequence: int = 1,
    payload_hash: str | None = None,
    is_snapshot: bool = False,
    event_type: StreamEventType = StreamEventType.NEW,
) -> WatchStreamEvent:
    return WatchStreamEvent(
        event_id=event_id,
        wallet_address=WALLET,
        observed_at_ms=observed_at_ms,
        received_at_ms=received_at_ms,
        event_type=event_type,
        sequence=sequence,
        payload_hash=payload_hash or event_id,
        is_snapshot=is_snapshot,
    )


def test_fresh_ordered_event_is_accepted_for_signal():
    decision = _engine().process_event(_event("e1", 1_000, 1_050, sequence=1))

    assert decision.action == RecoveryAction.KEEP_WATCHING
    assert decision.accepted_for_signal is True
    assert decision.backfill is None


def test_duplicate_event_is_dropped_and_never_signalled():
    engine = _engine()
    first = _event("e1", 1_000, 1_050, sequence=1, payload_hash="same")
    engine.process_event(first)

    duplicate = engine.process_event(_event("e2", 1_001, 1_060, sequence=2, payload_hash="same"))

    assert duplicate.action == RecoveryAction.DROP_DUPLICATE
    assert duplicate.accepted_for_signal is False
    assert duplicate.reason == "DUPLICATE_EVENT"


def test_snapshot_is_context_only_not_a_copy_signal():
    decision = _engine().process_event(
        _event("snapshot", 1_000, 1_050, sequence=1, is_snapshot=True, event_type=StreamEventType.SNAPSHOT)
    )

    assert decision.action == RecoveryAction.OBSERVE_ONLY
    assert decision.accepted_for_signal is False
    assert decision.reason == "SNAPSHOT_CONTEXT_ONLY"


def test_time_gap_plans_reconnect_and_bounded_backfill():
    engine = _engine()
    engine.process_event(_event("e1", 1_000, 1_050, sequence=1))

    decision = engine.process_event(_event("e2", 10_001, 10_050, sequence=2))

    assert decision.action == RecoveryAction.RECONNECT_AND_BACKFILL
    assert decision.accepted_for_signal is False
    assert decision.should_reconnect is True
    assert decision.backfill is not None
    assert decision.backfill.max_pages == 2
    assert "DATA_GAP_BY_TIME" in decision.warnings


def test_sequence_gap_plans_backfill_even_if_time_is_fresh():
    engine = _engine()
    engine.process_event(_event("e1", 1_000, 1_050, sequence=1))

    decision = engine.process_event(_event("e2", 2_000, 2_050, sequence=5))

    assert decision.action == RecoveryAction.RECONNECT_AND_BACKFILL
    assert decision.backfill is not None
    assert "DATA_GAP_BY_SEQUENCE" in decision.warnings


def test_stale_event_plans_recovery_and_blocks_signal():
    decision = _engine().process_event(_event("stale", 1_000, 10_001, sequence=1))

    assert decision.action == RecoveryAction.RECONNECT_AND_BACKFILL
    assert decision.accepted_for_signal is False
    assert decision.backfill is not None
    assert "STALE_EVENT" in decision.warnings


def test_idle_wallet_without_events_requests_reconnect_only():
    decision = _engine().evaluate_idle_wallet(WALLET, now_ms=10_000)

    assert decision.action == RecoveryAction.RECONNECT
    assert decision.should_reconnect is True
    assert decision.backfill is None


def test_idle_wallet_after_event_requests_reconnect_and_backfill():
    engine = _engine()
    engine.process_event(_event("e1", 1_000, 1_050, sequence=1))

    decision = engine.evaluate_idle_wallet(WALLET, now_ms=10_000)

    assert decision.action == RecoveryAction.RECONNECT_AND_BACKFILL
    assert decision.should_reconnect is True
    assert decision.backfill is not None
    assert decision.reason == "WATCH_IDLE_STALE"


def test_recovery_report_is_explicitly_read_only():
    decision = _engine().process_event(_event("stale", 1_000, 10_001, sequence=1))
    report = format_recovery_decision(decision)

    assert "realtime_recovery=read_only" in report
    assert "accepted_for_signal=false" in report
    assert "execution=forbidden" in report
    assert "profit_guarantee=false" in report


def test_realtime_recovery_plan_cli_outputs_read_only_backfill_plan():
    result = CliRunner().invoke(
        app,
        [
            "realtime-recovery-plan",
            "--stale-after-ms",
            "1000",
            "--event-gap-ms",
            "1000",
            "--sequence-gap",
            "3",
        ],
    )

    assert result.exit_code == 0
    assert "realtime_recovery=read_only" in result.output
    assert "action=RECONNECT_AND_BACKFILL" in result.output
    assert "backfill_max_pages=3" in result.output
    assert "execution=forbidden" in result.output
