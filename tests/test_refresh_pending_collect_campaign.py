from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "refresh_pending_collect_campaign_test",
        ROOT / "tools" / "refresh_pending_collect_campaign.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _manifest(*, status="PENDING", lease=None, completed_units=None, outputs=None):
    return {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": "market-test-v6",
        "kind": "market_collection",
        "creation_phase": "COLLECT",
        "phase_epoch": 4,
        "code_sha": "1" * 40,
        "config_sha256": "2" * 64,
        "work_plan_sha256": "3" * 64,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
        "status": status,
        "status_reason": "created",
        "updated_at": "2026-09-30T15:00:00Z",
        "chunk_index": 0,
        "attempts": 0,
        "consecutive_failures": 0,
        "no_progress_count": 0,
        "next_due_at": None,
        "cursor": {"duration_s": 3500, "generation": 0},
        "completed_units": completed_units or {},
        "lease": lease,
        "outputs": outputs or [],
        "checkpoint_lineage": [],
        "terminal_evidence_digest": None,
        "history": [],
    }


def _write(path: Path, row: dict) -> None:
    path.write_text(json.dumps(row, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _refresh(module, path: Path, history: Path, *, epoch=4):
    return module.refresh(
        manifest_path=path,
        history_dir=history,
        code_sha="a" * 40,
        config_sha256="b" * 64,
        work_plan_sha256="c" * 64,
        expected_phase_epoch=epoch,
    )


def test_refreshes_stale_unleased_nonproductive_collect_campaign(tmp_path) -> None:
    module = _module()
    manifest = tmp_path / "market.json"
    history = tmp_path / "history"
    _write(manifest, _manifest())

    result = _refresh(module, manifest, history)
    row = json.loads(manifest.read_text(encoding="utf-8"))

    assert result["refreshed"] is True
    assert row["code_sha"] == "a" * 40
    assert row["status"] == "PENDING"
    assert row["status_reason"] == "refresh_collect_after_code_fix"
    assert row["chunk_index"] == 0
    assert row["completed_units"] == {}
    assert "generation" not in row["cursor"]
    assert row["history"][-1]["event"] == "refresh_collect_after_code_fix"
    assert Path(result["archive_path"]).is_file()


def test_preserves_leased_collect_campaign(tmp_path) -> None:
    module = _module()
    manifest = tmp_path / "market.json"
    history = tmp_path / "history"
    original = _manifest(lease={"owner": "run-123", "token_sha256": "x"})
    _write(manifest, original)

    result = _refresh(module, manifest, history)

    assert result == {
        "refreshed": False,
        "reason": "leased_campaign_preserved",
        "campaign_id": "market-test-v6",
    }
    assert json.loads(manifest.read_text(encoding="utf-8")) == original


def test_preserves_collect_campaign_with_productive_completed_unit(tmp_path) -> None:
    module = _module()
    manifest = tmp_path / "market.json"
    history = tmp_path / "history"
    original = _manifest(
        status="CONTINUATION_REQUIRED",
        completed_units={
            "0": {
                "sha256": "d" * 64,
                "result": {"status": "COMPLETE", "release_tag": "data-v2-test"},
            }
        },
    )
    _write(manifest, original)

    result = _refresh(module, manifest, history)

    assert result["refreshed"] is False
    assert result["reason"] == "durable_or_productive_work_preserved"
    assert json.loads(manifest.read_text(encoding="utf-8")) == original


def test_rejects_phase_epoch_mismatch(tmp_path) -> None:
    module = _module()
    manifest = tmp_path / "market.json"
    history = tmp_path / "history"
    _write(manifest, _manifest())

    with pytest.raises(SystemExit, match="phase epoch changed"):
        _refresh(module, manifest, history, epoch=5)
