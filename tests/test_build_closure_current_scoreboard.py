from __future__ import annotations

import json

from tools.build_closure_report import _validated_current_scoreboard, digest


def _phase():
    return {
        "phase": "ANALYZE",
        "epoch": 3,
        "source_collection_epoch": 2,
    }


def _campaign():
    return {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": "analysis-e3-scoreboard-v2",
        "kind": "scoreboard",
        "creation_phase": "ANALYZE",
        "status": "COMPLETE",
        "phase_epoch": 3,
        "source_collection_epoch": 2,
        "dataset_selection_id": "phase-2-cutoff",
        "collection_cutoff_at_utc": "2026-09-29T10:56:59Z",
        "code_sha": "a" * 40,
    }


def _scoreboard():
    return {
        "schema_version": "hypersmart.economic_family_scoreboards.v2",
        "families": {
            "copy_vault": {"verdict": "MORE_DATA"},
            "lead_lag": {"verdict": "MORE_DATA"},
            "cross_venue_dislocation_v2": {"verdict": "KILL"},
        },
        "paper_read_only": True,
        "real_execution": False,
    }


def _write_receipt(root):
    campaign = _campaign()
    scoreboard = _scoreboard()
    body = {
        "schema": "alina.analysis_scoreboard_receipt.v1",
        "campaign_id": campaign["campaign_id"],
        "unit_id": "0",
        "phase_epoch": campaign["phase_epoch"],
        "source_collection_epoch": campaign["source_collection_epoch"],
        "collection_cutoff_at_utc": campaign["collection_cutoff_at_utc"],
        "dataset_selection_id": campaign["dataset_selection_id"],
        "code_sha": campaign["code_sha"],
        "evidence_repository": "Rapt0r06300/alina-smartflow-datasets-v2",
        "evidence_tag": "campaign-evidence-analysis-e3-scoreboard-v2-u0",
        "scoreboard_sha256": digest(scoreboard),
        "scoreboard": scoreboard,
        "environment_receipt_sha256": "b" * 64,
        "environment_provenance": {
            "os": "Linux",
            "python_version": "3.12.0",
            "dependency_digest": "c" * 64,
        },
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    body["receipt_digest"] = digest(body)
    (root / "catalog").mkdir(parents=True)
    (root / "catalog/ANALYSIS_SCOREBOARD_RECEIPT.json").write_text(
        json.dumps(body), encoding="utf-8"
    )
    return campaign, body


def test_closure_uses_only_current_epoch_scoreboard_receipt(tmp_path):
    campaign, receipt = _write_receipt(tmp_path)
    valid, scoreboard, loaded, reason = _validated_current_scoreboard(
        tmp_path, _phase(), [campaign]
    )
    assert valid is True
    assert reason == "CURRENT_SCOREBOARD_RECEIPT_VALID"
    assert loaded["receipt_digest"] == receipt["receipt_digest"]
    assert scoreboard["families"]["cross_venue_dislocation_v2"]["verdict"] == "KILL"


def test_closure_rejects_stale_or_tampered_scoreboard_receipt(tmp_path):
    campaign, receipt = _write_receipt(tmp_path)
    stale = _phase()
    stale["epoch"] = 4
    valid, _, _, reason = _validated_current_scoreboard(tmp_path, stale, [campaign])
    assert valid is False
    assert reason.startswith("CURRENT_SCOREBOARD_")

    receipt["scoreboard"]["families"]["copy_vault"]["verdict"] = "PROMOTE"
    (tmp_path / "catalog/ANALYSIS_SCOREBOARD_RECEIPT.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )
    valid, _, _, reason = _validated_current_scoreboard(tmp_path, _phase(), [campaign])
    assert valid is False
    assert reason in {
        "CURRENT_SCOREBOARD_RECEIPT_DIGEST_INVALID",
        "CURRENT_SCOREBOARD_HASH_MISMATCH",
    }
