from __future__ import annotations

import json
from pathlib import Path

from hl_observer.ops.runtime_contract import (
    campaign_binding_receipt,
    ccxt_execution_dependency_receipt,
    freeze_discovery_receipt,
    health_receipt_gate,
    partition_quarantine_receipt,
    publication_loop_receipt,
    release_atomicity_receipt,
    safe_replay_chain_receipt,
    websocket_snapshot_receipt,
    websocket_unique_users_receipt,
)


ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_ack_reconnect_and_dedup_are_causal():
    result = websocket_snapshot_receipt(
        [
            {"kind": "ACK"},
            {"native_id": "snapshot-1", "isSnapshot": True},
            {"native_id": "fill-1", "isSnapshot": False},
            {"native_id": "fill-1", "isSnapshot": False, "reconnect_id": "r2"},
        ]
    )
    assert result["status"] == "PROVEN"
    assert result["snapshot_count"] == 1
    assert result["causal_live_event_count"] == 1
    assert result["duplicates_removed"] == 1


def test_snapshot_without_marker_is_fail_closed():
    result = websocket_snapshot_receipt([{"kind": "ACK"}, {"native_id": "fill-1"}])
    assert result == {"status": "UNKNOWN", "reason": "snapshot_marker_or_identity_missing"}


def test_ten_unique_users_require_acknowledged_subscriptions():
    rows = [{"user_id": f"u-{i}", "ack": True} for i in range(10)]
    result = websocket_unique_users_receipt(rows)
    assert result == {"status": "PROVEN", "unique_users": 10, "expected_users": 10}
    assert websocket_unique_users_receipt(rows[:-1])["status"] == "UNKNOWN"


def test_health_receipt_is_absent_safe_and_schema_bound(tmp_path):
    assert health_receipt_gate(tmp_path / "missing.json", expected_schema=1)["status"] == "UNKNOWN"
    payload = {
        "schema_version": 1,
        "status": "HEALTHY",
        "source_sha256": "a" * 64,
        "created_at_utc": "2026-11-04T00:00:00Z",
        "checks": {"ws": True, "safe": True},
    }
    path = tmp_path / "health.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert health_receipt_gate(path, expected_schema=1)["status"] == "PROVEN"
    payload["checks"]["safe"] = False
    assert health_receipt_gate(payload, expected_schema=1)["status"] == "UNKNOWN"


def test_campaign_binding_requires_exact_code_and_dataset():
    result = campaign_binding_receipt(
        code_sha="b" * 40,
        manifest_code_sha="b" * 40,
        dataset_selection_id="copy-vault-safe-001",
        expected_dataset_selection_id="copy-vault-safe-001",
        phase_epoch=3,
    )
    assert result["status"] == "PROVEN"
    assert campaign_binding_receipt(
        code_sha="b" * 40,
        manifest_code_sha="c" * 40,
        dataset_selection_id="copy-vault-safe-001",
        expected_dataset_selection_id="copy-vault-safe-001",
        phase_epoch=3,
    )["status"] == "UNKNOWN"


def test_eight_quarantine_partitions_reconcile_counts():
    rows = [
        {
            "partition_id": f"p-{i}",
            "status": "QUARANTINED",
            "sha256": f"{i:064x}",
            "record_count": 2,
            "unique_count": 2,
        }
        for i in range(8)
    ]
    assert partition_quarantine_receipt(
        rows, total_count=16, total_unique_count=16
    )["status"] == "PROVEN"
    rows[0]["unique_count"] = 3
    assert partition_quarantine_receipt(
        rows, total_count=16, total_unique_count=16
    )["status"] == "UNKNOWN"


def test_safe_replay_chain_is_sha_bound():
    rows = {
        name: {
            "status": "PROVEN",
            "code_sha": "d" * 40,
            "dataset_sha256": "e" * 64,
            "safe": True,
        }
        for name in ("sync", "book_loader", "replay")
    }
    rows["replay"]["replay_rows"] = 12
    assert safe_replay_chain_receipt(rows)["status"] == "PROVEN"
    rows["replay"]["code_sha"] = "f" * 40
    assert safe_replay_chain_receipt(rows)["status"] == "UNKNOWN"


def test_discovery_continues_after_two_freezes():
    cycles = [
        {
            "cycle_id": "c1",
            "freeze_status": "FROZEN",
            "discovery_status": "CONTINUED",
            "continued_after_freeze": True,
        },
        {
            "cycle_id": "c2",
            "freeze_status": "FROZEN",
            "discovery_status": "CONTINUED",
            "continued_after_freeze": True,
        },
    ]
    assert freeze_discovery_receipt(cycles)["status"] == "PROVEN"
    cycles[1]["continued_after_freeze"] = False
    assert freeze_discovery_receipt(cycles)["status"] == "UNKNOWN"


def test_release_requires_one_complete_sha_bound_publication():
    common = {"status": "PUBLISHED", "sha256": "1" * 64}
    asset = dict(common)
    manifest = dict(common)
    receipt = dict(common)
    checkpoint = {**common, "resume_idempotent": True, "partial": False}
    assert release_atomicity_receipt(
        asset=asset, manifest=manifest, receipt=receipt, checkpoint=checkpoint
    )["status"] == "PROVEN"
    manifest["sha256"] = "2" * 64
    assert release_atomicity_receipt(
        asset=asset, manifest=manifest, receipt=receipt, checkpoint=checkpoint
    )["status"] == "UNKNOWN"


def test_report_workflow_has_no_bot_loop_or_stale_head():
    text = (ROOT / ".github/workflows/alina-canonical-closure-report.yml").read_text(
        encoding="utf-8"
    )
    assert publication_loop_receipt(text)["status"] == "PROVEN"


def test_ccxt_is_discovery_only_and_never_execution_capable():
    imports = [
        {
            "package": "ccxt",
            "module": "hl_observer.markets.ccxt_universe",
            "execution_capable": False,
            "order_methods": False,
        }
    ]
    assert ccxt_execution_dependency_receipt(imports)["status"] == "PROVEN"
    imports[0]["order_methods"] = True
    assert ccxt_execution_dependency_receipt(imports)["status"] == "UNKNOWN"
