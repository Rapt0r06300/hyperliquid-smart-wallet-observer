from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from tools.finalize_analysis_drain import finalize


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _manifest(*, status: str = "STUCK", completed: bool = False) -> dict:
    return {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": "market-e2",
        "kind": "market_collection",
        "creation_phase": "COLLECT",
        "phase_epoch": 2,
        "status": status,
        "status_reason": "worker_started",
        "completed_units": {"0": {"sha256": "a" * 64}} if completed else {},
        "checkpoint_lineage": [],
        "lease": None,
        "next_due_at": None,
        "history": [],
    }


def test_finalize_expired_drain_without_checkpoint_is_unavailable(tmp_path: Path) -> None:
    phase = tmp_path / "control/alina-phase.json"
    campaigns = tmp_path / "catalog/campaigns"
    _write(
        phase,
        {
            "phase": "ANALYZE",
            "epoch": 3,
            "source_collection_epoch": 2,
            "collection_cutoff_at_utc": "2026-09-29T10:00:00Z",
        },
    )
    manifest = campaigns / "market-e2.json"
    _write(manifest, _manifest())

    result = finalize(
        phase_path=phase,
        campaign_root=campaigns,
        drain_grace_s=60,
        now=datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc),
    )

    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert result["changed"] == 1
    assert saved["status"] == "UNAVAILABLE"
    assert saved["lease"] is None
    assert len(saved["terminal_evidence_digest"]) == 64


def test_finalize_expired_drain_with_checkpoint_is_partial(tmp_path: Path) -> None:
    phase = tmp_path / "control/alina-phase.json"
    campaigns = tmp_path / "catalog/campaigns"
    _write(
        phase,
        {
            "phase": "ANALYZE",
            "epoch": 3,
            "source_collection_epoch": 2,
            "collection_cutoff_at_utc": "2026-09-29T10:00:00Z",
        },
    )
    manifest = campaigns / "market-e2.json"
    _write(manifest, _manifest(completed=True))

    result = finalize(
        phase_path=phase,
        campaign_root=campaigns,
        drain_grace_s=60,
        now=datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc),
    )

    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert result["changed"] == 1
    assert saved["status"] == "PARTIAL"


def test_live_pre_deadline_lease_is_not_finalized(tmp_path: Path) -> None:
    phase = tmp_path / "control/alina-phase.json"
    campaigns = tmp_path / "catalog/campaigns"
    _write(
        phase,
        {
            "phase": "ANALYZE",
            "epoch": 3,
            "source_collection_epoch": 2,
            "collection_cutoff_at_utc": "2026-09-29T10:00:00Z",
        },
    )
    row = _manifest(status="RUNNING")
    row["lease"] = {"expires_at": "2026-09-29T10:50:00Z"}
    manifest = campaigns / "market-e2.json"
    _write(manifest, row)

    result = finalize(
        phase_path=phase,
        campaign_root=campaigns,
        drain_grace_s=3600,
        now=datetime(2026, 9, 29, 10, 30, tzinfo=timezone.utc),
    )

    assert result["changed"] == 0
    assert result["remaining_active"] == 1
    assert json.loads(manifest.read_text(encoding="utf-8"))["status"] == "RUNNING"

def test_predeadline_inactive_source_campaign_is_closed_without_checkpoint(tmp_path: Path) -> None:
    phase = tmp_path / "control/alina-phase.json"
    campaigns = tmp_path / "catalog/campaigns"
    _write(
        phase,
        {
            "phase": "ANALYZE",
            "epoch": 3,
            "source_collection_epoch": 2,
            "collection_cutoff_at_utc": "2026-09-29T10:00:00Z",
        },
    )
    manifest = campaigns / "market-e2.json"
    _write(manifest, _manifest(status="PENDING"))

    result = finalize(
        phase_path=phase,
        campaign_root=campaigns,
        drain_grace_s=3600,
        now=datetime(2026, 9, 29, 10, 30, tzinfo=timezone.utc),
    )

    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert result["changed"] == 1
    assert result["remaining_active"] == 0
    assert saved["status"] == "UNAVAILABLE"
    assert saved["status_reason"] == "analysis_drain_inactive_lease_without_checkpoint"


def test_predeadline_inactive_source_campaign_keeps_checkpoint_as_partial(tmp_path: Path) -> None:
    phase = tmp_path / "control/alina-phase.json"
    campaigns = tmp_path / "catalog/campaigns"
    _write(
        phase,
        {
            "phase": "ANALYZE",
            "epoch": 3,
            "source_collection_epoch": 2,
            "collection_cutoff_at_utc": "2026-09-29T10:00:00Z",
        },
    )
    manifest = campaigns / "market-e2.json"
    _write(manifest, _manifest(status="CONTINUATION_REQUIRED", completed=True))

    result = finalize(
        phase_path=phase,
        campaign_root=campaigns,
        drain_grace_s=3600,
        now=datetime(2026, 9, 29, 10, 30, tzinfo=timezone.utc),
    )

    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert result["changed"] == 1
    assert result["remaining_active"] == 0
    assert saved["status"] == "PARTIAL"
    assert saved["status_reason"] == "analysis_drain_inactive_lease_with_checkpoint"

