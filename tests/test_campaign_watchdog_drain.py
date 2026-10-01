from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from tools.campaign_watchdog import _dispatch_successor, _reconcile_drain_stuck, _reconcile_finished_owner


def _phase():
    return {
        "phase": "ANALYZE",
        "analysis_stage": "DRAIN",
        "epoch": 3,
        "source_collection_epoch": 2,
        "collection_cutoff_at_utc": "2026-09-29T10:56:59Z",
    }


def _row(*, completed=None, acquired_at="2026-09-29T10:52:00Z"):
    return {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": "market-drain",
        "kind": "market_collection",
        "creation_phase": "COLLECT",
        "phase_epoch": 2,
        "status": "STUCK",
        "stuck_reason": "LEASE_EXPIRED_REQUIRES_RECONCILIATION",
        "lease": None,
        "completed_units": completed or {},
        "history": [{
            "event": "WATCHDOG_LEASE_EXPIRED",
            "previous_lease": {
                "acquired_at": acquired_at,
                "expires_at": "2026-09-29T16:37:00Z",
            },
        }],
    }


def test_drain_terminalizes_expired_claim_without_durable_progress():
    row = _row()
    assert _reconcile_drain_stuck(
        row, _phase(), datetime(2026, 9, 30, tzinfo=timezone.utc)
    )
    assert row["status"] == "UNAVAILABLE"
    assert row["status_reason"] == "DRAIN_CUTOFF_INTERRUPTED_WITHOUT_DURABLE_PROGRESS"
    assert row["lease"] is None
    assert len(row["terminal_evidence_digest"]) == 64


def test_drain_preserves_durable_progress_as_partial():
    row = _row(completed={"0": {"sha256": "a" * 64}})
    assert _reconcile_drain_stuck(
        row, _phase(), datetime(2026, 9, 30, tzinfo=timezone.utc)
    )
    assert row["status"] == "PARTIAL"
    assert row["status_reason"] == "DRAIN_CUTOFF_INTERRUPTED_AFTER_DURABLE_PROGRESS"


def test_drain_rejects_claim_started_after_cutoff():
    row = _row(acquired_at="2026-09-29T11:00:00Z")
    assert _reconcile_drain_stuck(
        row, _phase(), datetime(2026, 9, 30, tzinfo=timezone.utc)
    )
    assert row["status"] == "FAILED"
    assert row["status_reason"] == "DRAIN_CLAIM_STARTED_AFTER_CUTOFF"


def test_non_drain_phase_does_not_rewrite_stuck_campaign():
    row = _row()
    phase = _phase()
    phase["analysis_stage"] = "QUALITY"
    assert not _reconcile_drain_stuck(
        row, phase, datetime(2026, 9, 30, tzinfo=timezone.utc)
    )
    assert row["status"] == "STUCK"

def test_finished_owner_run_revokes_live_lease_immediately():
    row = {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": "analysis-e3-resume-proof-v1",
        "kind": "replay",
        "status": "RUNNING",
        "lease": {
            "owner_run_id": "12345",
            "acquired_at": "2026-09-30T13:00:00Z",
            "expires_at": "2026-09-30T19:00:00Z",
        },
        "history": [],
    }
    now = datetime(2026, 9, 30, 13, 30, tzinfo=timezone.utc)
    assert _reconcile_finished_owner(
        row,
        now,
        run_state=lambda run_id: ("completed", "failure"),
    )
    assert row["lease"] is None
    assert row["status"] == "STUCK"
    assert row["status_reason"] == "OWNER_RUN_COMPLETED_WITH_ACTIVE_LEASE"
    assert row["stuck_reason"] == "OWNER_RUN_COMPLETED_WITH_ACTIVE_LEASE"
    assert row["history"][-1]["owner_run_id"] == "12345"
    assert row["history"][-1]["owner_run_conclusion"] == "failure"


def test_active_owner_run_keeps_live_lease():
    row = {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": "analysis-e3-replay-v2",
        "kind": "replay",
        "status": "RUNNING",
        "lease": {"owner_run_id": "999", "expires_at": "2026-09-30T19:00:00Z"},
        "history": [],
    }
    now = datetime(2026, 9, 30, 13, 30, tzinfo=timezone.utc)
    assert not _reconcile_finished_owner(
        row,
        now,
        run_state=lambda run_id: ("in_progress", ""),
    )
    assert row["status"] == "RUNNING"
    assert row["lease"]["owner_run_id"] == "999"

def test_dispatch_successor_retries_transient_rate_limit(monkeypatch):
    row = {
        "campaign_id": "market-retry",
        "phase_epoch": 7,
        "chunk_index": 3,
        "cursor": {"last_run_id": ""},
    }
    calls = []
    responses = [
        SimpleNamespace(returncode=1, stderr="HTTP 403: API rate limit exceeded for installation", stdout=""),
        SimpleNamespace(returncode=0, stderr="", stdout=""),
    ]

    def fake_run(command, **kwargs):
        calls.append(command)
        return responses.pop(0)

    sleeps = []
    monkeypatch.setattr("tools.campaign_watchdog.subprocess.run", fake_run)
    monkeypatch.setattr("tools.campaign_watchdog.time.sleep", lambda seconds: sleeps.append(seconds))

    ok, detail = _dispatch_successor(
        row,
        "Rapt0r06300/hyperliquid-smart-wallet-observer",
        datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc),
    )

    assert ok is True
    assert detail == "dispatched"
    assert len(calls) == 2
    assert sleeps == [5]
    assert row["cursor"]["successor_dispatch_at_utc"] == "2026-10-01T14:00:00Z"


def test_dispatch_successor_stops_after_bounded_transient_retries(monkeypatch):
    row = {
        "campaign_id": "market-retry-bounded",
        "phase_epoch": 7,
        "chunk_index": 4,
        "cursor": {"last_run_id": ""},
    }
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=1,
            stderr="HTTP 403: API rate limit exceeded for installation",
            stdout="",
        )

    sleeps = []
    monkeypatch.setattr("tools.campaign_watchdog.subprocess.run", fake_run)
    monkeypatch.setattr("tools.campaign_watchdog.time.sleep", lambda seconds: sleeps.append(seconds))

    ok, detail = _dispatch_successor(
        row,
        "Rapt0r06300/hyperliquid-smart-wallet-observer",
        datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc),
    )

    assert ok is False
    assert "bounded transient dispatch retry exhausted" in detail
    assert len(calls) == 6
    assert sleeps == [5, 20, 45, 60, 60]
    assert "successor_dispatch_at_utc" not in row["cursor"]

