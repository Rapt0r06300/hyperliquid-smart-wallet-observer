"""Two-speed Copy-Vault REST breadth must not be confused with WS user limits."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[1] / "tools" / "build_copy_vault_coverage_receipt.py"
    spec = importlib.util.spec_from_file_location("copy_vault_receipt_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _receipt(tmp_path, monkeypatch, *, mode="two_speed_broad_rest_priority_ws",
             ws_cap=10, vault_count=12):
    monkeypatch.chdir(tmp_path)
    selection = tmp_path / "catalog" / "copy_vault_selections" / "e8" / "sample.json"
    selection.parent.mkdir(parents=True)
    selection.write_text(json.dumps({
        "vaults": [{"address": f"0x{n:040x}"} for n in range(vault_count)],
        "schema": "alina.copy_vault_selection.v2",
    }), encoding="utf-8")
    cursor = {
        "selection_sha256": hashlib.sha256(selection.read_bytes()).hexdigest(),
        "selection_file": str(selection),
        "vault_shard_count": 1,
        "vault_shard_index": 0,
        "max_vaults": vault_count,
        "copy_vault_mode": mode,
        "max_ws_vaults": ws_cap,
    }
    campaign_dir = tmp_path / "catalog" / "campaigns"
    campaign_dir.mkdir(parents=True)
    (campaign_dir / "copy-vault-test.json").write_text(json.dumps({
        "kind": "copy_vault_collection",
        "schema_version": "alina.resumable_campaign.v2",
        "phase_epoch": 8,
        "created_at": "2026-10-13T12:00:00Z",
        "campaign_id": "copy-vault-test",
        "cursor": cursor,
        "status": "RUNNING",
        "completed_units": {},
    }), encoding="utf-8")
    phase_path = tmp_path / "control" / "alina-phase.json"
    phase_path.parent.mkdir()
    phase_path.write_text(json.dumps({"phase": "COLLECT", "epoch": 8}), encoding="utf-8")
    return _module().build_receipt(
        campaign_dir=campaign_dir, phase_path=phase_path,
        output=tmp_path / "catalog" / "COPY_VAULT_COVERAGE_RECEIPT.json",
    )


def test_broad_rest_twelve_vaults_with_ten_ws_users_is_structurally_valid(tmp_path, monkeypatch):
    receipt = _receipt(tmp_path, monkeypatch, ws_cap=10, vault_count=12)
    plan = receipt["authoritative_plan"]
    assert plan["collection_mode"] == "two_speed_broad_rest_priority_ws"
    assert plan["users_per_largest_lane"] == 12
    assert plan["ws_users_per_largest_lane"] == 10
    assert plan["broad_rest_universe_count"] == 12
    assert plan["ws_subscription_limit_verified"] is True
    assert plan["plan_valid"] is True
    assert receipt["reconciliation"]["ten_user_limit_respected"] is True
    assert receipt["status"] == "MORE_DATA"
    assert receipt["reconciliation"]["publication_complete"] is False


def test_broad_rest_oversized_ws_budget_is_blocked(tmp_path, monkeypatch):
    receipt = _receipt(tmp_path, monkeypatch, ws_cap=11)
    assert receipt["status"] == "UNAVAILABLE"
    assert receipt["candidate_campaign_count"] == 0
    assert len(receipt["invalid_manifest_paths"]) == 1


def test_legacy_ws_lane_cannot_hold_twelve_vaults(tmp_path, monkeypatch):
    receipt = _receipt(tmp_path, monkeypatch, mode="legacy_sharded_ws", vault_count=12)
    assert receipt["status"] == "BLOCKED"
    assert receipt["reconciliation"]["ten_user_limit_respected"] is False


def test_unknown_copy_vault_mode_refused(tmp_path, monkeypatch):
    receipt = _receipt(tmp_path, monkeypatch, mode="unknown_mode")
    assert receipt["status"] == "UNAVAILABLE"
    assert receipt["candidate_campaign_count"] == 0


def test_broad_rest_missing_ws_budget_is_refused(tmp_path, monkeypatch):
    receipt = _receipt(tmp_path, monkeypatch, ws_cap=None)
    assert receipt["status"] == "UNAVAILABLE"
    assert receipt["candidate_campaign_count"] == 0
