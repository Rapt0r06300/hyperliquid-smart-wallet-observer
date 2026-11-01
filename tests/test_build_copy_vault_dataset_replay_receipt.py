from __future__ import annotations

from pathlib import Path

from tools.build_copy_vault_dataset_replay_receipt import build_receipt


def test_dataset_train_only_run_stays_unmeasurable(tmp_path: Path) -> None:
    campaign = {
        "schema_version": "hypersmart.economic_campaign_evidence.v1",
        "objective_status": "NON_ATTEINT",
        "paper_read_only": True,
        "real_execution": False,
        "source_status": "KILL_TRAIN_INSUFFICIENT_EXECUTABLE_EPISODES",
        "dataset_provenance": {
            "dataset_fingerprint": "a" * 64,
            "files": [{"exists": True, "fingerprint": "b" * 64, "path": "vault_fills_live.jsonl"}],
        },
        "oos": {"sample_count": None, "anti_lookahead_receipt_valid": False},
        "forward": {"sample_count": None, "anti_lookahead_receipt_valid": False},
    }
    provenance = {"schema": "hypersmart.dataset_selection_provenance.v4"}
    campaign_path = tmp_path / "campaign.json"
    provenance_path = tmp_path / "provenance.json"
    campaign_path.write_text("{}", encoding="utf-8")
    provenance_path.write_text("{}", encoding="utf-8")
    receipt = build_receipt(
        campaign,
        provenance,
        task_scope="H-T99",
        head_sha="a" * 40,
        campaign_path=campaign_path,
        provenance_path=provenance_path,
    )
    assert receipt["evidence_status"] == "UNMEASURABLE"
    assert receipt["decision"] == "NO_GO"
    assert receipt["claims"]["missing_values_not_zeroed"] is True
    assert "OOS_FROZEN_REPLAY_MISSING" in receipt["missing_evidence"]


def test_t119_never_treats_train_replay_as_ablation(tmp_path: Path) -> None:
    campaign = {
        "paper_read_only": True,
        "real_execution": False,
        "dataset_provenance": {"dataset_fingerprint": "a" * 64, "files": []},
        "oos": None,
        "forward": None,
    }
    provenance = {}
    campaign_path = tmp_path / "campaign.json"
    provenance_path = tmp_path / "provenance.json"
    campaign_path.write_text("{}", encoding="utf-8")
    provenance_path.write_text("{}", encoding="utf-8")
    receipt = build_receipt(
        campaign,
        provenance,
        task_scope="H-T119",
        head_sha="a" * 40,
        campaign_path=campaign_path,
        provenance_path=provenance_path,
    )
    assert receipt["claims"]["ablation_follower_count"] is False
    assert "CROWDING_FOLLOWER_ABLATION_MISSING" in receipt["missing_evidence"]
