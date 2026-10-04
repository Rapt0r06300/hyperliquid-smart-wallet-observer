from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from tools.campaign_watchdog import (
    _dispatch_market_handoff,
    _dispatch_successor,
    _reconcile_drain_stuck,
    _reconcile_finished_owner,
    _select_market_handoff_successor,
    _terminalize_superseded_stuck,
)


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

def test_stuck_market_campaign_terminalizes_when_newer_equivalent_progresses():
    old = {
        "campaign_id": "market-e6-0-old",
        "kind": "market_collection",
        "status": "STUCK",
        "status_reason": "durable_publication_failed",
        "phase_epoch": 6,
        "created_at": "2026-10-01T04:55:00+00:00",
        "completed_units": {"0": {"sha256": "a" * 64}},
        "cursor": {
            "market_shard_index": 0,
            "universe_digest": "u" * 64,
            "plan_sha256": "p" * 64,
        },
        "history": [],
    }
    replacement = {
        "campaign_id": "market-e6-0-new",
        "kind": "market_collection",
        "status": "RUNNING",
        "attempts": 1,
        "phase_epoch": 6,
        "created_at": "2026-10-01T05:07:00+00:00",
        "lease": {"owner_run_id": "123"},
        "cursor": {
            "market_shard_index": 0,
            "universe_digest": "u" * 64,
            "plan_sha256": "p" * 64,
        },
    }

    assert _terminalize_superseded_stuck(
        old, replacement, datetime(2026, 10, 1, 15, 10, tzinfo=timezone.utc)
    )
    assert old["status"] == "FAILED"
    assert old["status_reason"] == "SUPERSEDED_BY_NEWER_MARKET_CAMPAIGN"
    assert old["history"][-1]["replacement_campaign_id"] == "market-e6-0-new"
    assert len(old["terminal_evidence_digest"]) == 64


def test_stuck_market_campaign_not_hidden_by_unprogressed_replacement():
    old = {
        "campaign_id": "market-e6-0-old",
        "kind": "market_collection",
        "status": "STUCK",
        "phase_epoch": 6,
        "created_at": "2026-10-01T04:55:00+00:00",
        "cursor": {
            "market_shard_index": 0,
            "universe_digest": "u" * 64,
            "plan_sha256": "p" * 64,
        },
        "history": [],
    }
    replacement = {
        "campaign_id": "market-e6-0-new",
        "kind": "market_collection",
        "status": "PENDING",
        "attempts": 0,
        "phase_epoch": 6,
        "created_at": "2026-10-01T05:07:00+00:00",
        "cursor": {
            "market_shard_index": 0,
            "universe_digest": "u" * 64,
            "plan_sha256": "p" * 64,
        },
    }

    assert not _terminalize_superseded_stuck(
        old, replacement, datetime(2026, 10, 1, 15, 10, tzinfo=timezone.utc)
    )
    assert old["status"] == "STUCK"

def _market_handoff_row(
    campaign_id: str,
    *,
    shard: int,
    status: str,
    created_at: str,
    acquired_at: str | None = None,
    owner_run_id: str | None = None,
):
    lease = None
    if acquired_at is not None:
        lease = {
            "acquired_at": acquired_at,
            "expires_at": "2026-10-04T06:00:00Z",
            "owner_run_id": owner_run_id or "run-predecessor",
        }
    return {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": campaign_id,
        "kind": "market_collection",
        "creation_phase": "COLLECT",
        "phase_epoch": 6,
        "status": status,
        "created_at": created_at,
        "updated_at": created_at,
        "chunk_index": 0,
        "lease": lease,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
        "cursor": {
            "duration_s": 3500,
            "market_shard_count": 16,
            "market_shard_index": shard,
            "universe_digest": "a" * 64,
            "plan_sha256": "b" * 64,
        },
        "history": [],
    }


def test_market_handoff_selects_newest_pending_same_shard_when_due():
    predecessor = _market_handoff_row(
        "market-old",
        shard=3,
        status="RUNNING",
        created_at="2026-10-04T00:00:00Z",
        acquired_at="2026-10-04T00:00:00Z",
    )
    older = _market_handoff_row(
        "market-next-1",
        shard=3,
        status="PENDING",
        created_at="2026-10-04T00:20:00Z",
    )
    newest = _market_handoff_row(
        "market-next-2",
        shard=3,
        status="PENDING",
        created_at="2026-10-04T00:35:00Z",
    )
    wrong_shard = _market_handoff_row(
        "market-wrong",
        shard=4,
        status="PENDING",
        created_at="2026-10-04T00:40:00Z",
    )

    successor, reason = _select_market_handoff_successor(
        predecessor,
        [older, newest, wrong_shard],
        datetime(2026, 10, 4, 0, 48, tzinfo=timezone.utc),
    )

    assert reason == "handoff_ready"
    assert successor is newest


def test_market_handoff_does_not_dispatch_too_early():
    predecessor = _market_handoff_row(
        "market-old",
        shard=3,
        status="RUNNING",
        created_at="2026-10-04T00:00:00Z",
        acquired_at="2026-10-04T00:00:00Z",
    )
    successor = _market_handoff_row(
        "market-next",
        shard=3,
        status="PENDING",
        created_at="2026-10-04T00:10:00Z",
    )

    selected, reason = _select_market_handoff_successor(
        predecessor,
        [successor],
        datetime(2026, 10, 4, 0, 20, tzinfo=timezone.utc),
    )

    assert selected is None
    assert reason == "handoff_not_due"


def test_dispatch_market_handoff_targets_distinct_successor_and_records_lineage(monkeypatch):
    predecessor = _market_handoff_row(
        "market-old",
        shard=3,
        status="RUNNING",
        created_at="2026-10-04T00:00:00Z",
        acquired_at="2026-10-04T00:00:00Z",
        owner_run_id="123456",
    )
    successor = _market_handoff_row(
        "market-next",
        shard=3,
        status="PENDING",
        created_at="2026-10-04T00:30:00Z",
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("tools.campaign_watchdog.subprocess.run", fake_run)

    ok, detail = _dispatch_market_handoff(
        predecessor,
        successor,
        "Rapt0r06300/hyperliquid-smart-wallet-observer",
        datetime(2026, 10, 4, 0, 48, tzinfo=timezone.utc),
    )

    assert ok is True
    assert detail == "handoff_dispatched"
    command = calls[0]
    assert "campaign_id=market-next" in command
    assert "predecessor_run_id=123456" in command
    assert "generation=1" in command
    assert predecessor["cursor"]["hot_handoff_successor_campaign_id"] == "market-next"
    assert predecessor["history"][-1]["event"] == "HOT_HANDOFF_SUCCESSOR_DISPATCHED"

