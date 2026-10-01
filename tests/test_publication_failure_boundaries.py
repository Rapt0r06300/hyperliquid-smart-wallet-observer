from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.reconcile_publication_consistency import reconcile


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _phase(root: Path, epoch: int = 3) -> Path:
    path = root / "control/alina-phase.json"
    _write_json(path, {"phase": "ANALYZE", "epoch": epoch})
    return path


def _campaign(root: Path, *, epoch: int = 3) -> tuple[Path, dict]:
    result_sha = "c" * 64
    campaign = {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": "analysis-e3-replay-v2",
        "kind": "replay",
        "creation_phase": "ANALYZE",
        "phase_epoch": epoch,
        "source_collection_epoch": 2,
        "code_sha": "a" * 40,
        "status": "COMPLETE",
        "completed_units": {
            "0": {
                "sha256": result_sha,
                "result": {
                    "status": "COMPLETE",
                    "durable_persisted": True,
                    "evidence_release_tag": "campaign-evidence-analysis-e3-replay-v2-u0",
                },
            }
        },
        "cursor": {"checkpoint_id": result_sha},
    }
    path = root / "catalog/campaigns" / f"{campaign['campaign_id']}.json"
    _write_json(path, campaign)
    return path, campaign


def _receipt(root: Path, manifest_path: Path, campaign: dict) -> Path:
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    receipt = {
        "schema": "alina.publication_receipt.v2",
        "receipt_id": f"{campaign['campaign_id']}:u0",
        "campaign_id": campaign["campaign_id"],
        "unit_id": "0",
        "kind": "replay",
        "status": "COMPLETE",
        "phase": "ANALYZE",
        "phase_epoch": 3,
        "code_sha": campaign["code_sha"],
        "dataset_generation": "V2_FRESH",
        "source_collection_epoch": 2,
        "collection_cutoff_at_utc": "2026-09-29T10:56:59Z",
        "dataset_selection_id": "selection-a",
        "checkpoint_id": campaign["completed_units"]["0"]["sha256"],
        "analysis_stage": "REPLAY",
        "result_sha256": "d" * 64,
        "payload_digest": "e" * 64,
        "alina_head": campaign["code_sha"],
        "dataset_head": "b" * 40,
        "manifest_sha256": manifest_sha,
        "publication_state": "RELEASE_AND_RECEIPT_WRITTEN",
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    path = root / "catalog/receipts" / f"{campaign['campaign_id']}-u0.json"
    _write_json(path, receipt)
    return path


def test_current_epoch_durable_checkpoint_without_receipt_fails_closed(tmp_path):
    phase_path = _phase(tmp_path, 3)
    _campaign(tmp_path, epoch=3)

    report = reconcile(
        tmp_path / "catalog/receipts",
        tmp_path / "catalog/campaigns",
        phase_path=phase_path,
    )

    assert report["missing_receipts"] == 1
    assert report["error_count"] == 1
    assert report["errors"][0]["code"] == "DURABLE_UNIT_RECEIPT_MISSING"


def test_historical_pre_receipt_campaign_is_not_retroactively_rewritten(tmp_path):
    phase_path = _phase(tmp_path, 3)
    _campaign(tmp_path, epoch=2)

    report = reconcile(
        tmp_path / "catalog/receipts",
        tmp_path / "catalog/campaigns",
        phase_path=phase_path,
    )

    assert report["missing_receipts"] == 0
    assert report["error_count"] == 0


def test_atomic_checkpoint_plus_receipt_reconciles(tmp_path):
    phase_path = _phase(tmp_path, 3)
    manifest_path, campaign = _campaign(tmp_path, epoch=3)
    _receipt(tmp_path, manifest_path, campaign)

    report = reconcile(
        tmp_path / "catalog/receipts",
        tmp_path / "catalog/campaigns",
        phase_path=phase_path,
    )

    assert report["checked"] == 1
    assert report["missing_receipts"] == 0
    assert report["error_count"] == 0


def test_worker_commits_checkpoint_and_receipt_in_one_commit():
    text = (ROOT / ".github/workflows/resumable-campaign-worker.yml").read_text(
        encoding="utf-8"
    )
    checkpoint = text.index("- name: Publish final campaign checkpoint")
    commit = text.index('git commit -m "campaign: checkpoint $CAMPAIGN_ID"', checkpoint)
    receipt = text.index("python tools/record_publication_receipt.py", checkpoint)

    assert receipt < commit
    assert 'RESULT_STATUS="$(python -c' in text[checkpoint:commit]
    assert 'if [ "$RESULT_STATUS" = "COMPLETE" ] && [ "$DURABLE_OUTCOME" = "success" ]; then' in text[checkpoint:commit]

    legacy = text.index("- name: Record publication receipt after final checkpoint")
    legacy_block = text[legacy : legacy + 500]
    assert "if: ${{ false }}" in legacy_block
