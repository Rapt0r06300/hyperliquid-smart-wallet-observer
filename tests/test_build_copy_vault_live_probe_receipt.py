from __future__ import annotations

import json
from pathlib import Path

from tools.build_copy_vault_live_probe_receipt import build_receipt


def test_summary_never_becomes_causal_proof(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    selection_path = tmp_path / "selection.json"
    summary_path.write_text("{}", encoding="utf-8")
    selection_path.write_text("[]", encoding="utf-8")
    receipt = build_receipt(
        {
            "schema": "alina.copy_vault_cloud_window.v2",
            "collection_run_id": "run-1",
            "read_only": True,
            "real_execution": False,
            "live_fill_counts": {"vault": 4},
            "l2_frames": 2,
            "l2_diagnostics": {"received_frames": 2},
            "subscription_diagnostics": {"acknowledged": 1},
        },
        summary_path=summary_path,
        selection_path=selection_path,
        head_sha="a" * 40,
    )
    assert receipt["evidence_status"] == "UNMEASURABLE"
    assert receipt["decision"] == "NO_GO"
    assert receipt["kind"] == "safe_replay"
    assert receipt["real_execution"] is False
    assert receipt["claims"]["causal_post_ack_fill_proven"] is False
    assert receipt["observation"]["live_fill_total_reported"] == 4
    assert "ROW_LEVEL_CAUSAL_LIVE_WS_RECEIPT_MISSING" in receipt["observation"]["missing_evidence"]


def test_live_probe_can_be_role_bound_for_l4_without_changing_observations(
    tmp_path: Path,
) -> None:
    summary_path = tmp_path / "summary.json"
    selection_path = tmp_path / "selection.json"
    summary_path.write_text("{}", encoding="utf-8")
    selection_path.write_text("[]", encoding="utf-8")
    receipt = build_receipt(
        {
            "schema": "alina.copy_vault_cloud_window.v2",
            "collection_run_id": "run-1",
            "read_only": True,
            "real_execution": False,
            "live_fill_counts": {"vault": 4},
            "l2_frames": 2,
            "l2_diagnostics": {"received_frames": 2},
            "subscription_diagnostics": {"acknowledged": 1},
        },
        summary_path=summary_path,
        selection_path=selection_path,
        head_sha="a" * 40,
        evidence_kind="l4_capture",
    )
    assert receipt["kind"] == "l4_capture"
    assert receipt["observation"]["live_fill_total_reported"] == 4
    assert receipt["claims"]["l4_fill_l2_pairing_proven"] is False


def test_empty_causal_rows_remain_unmeasurable_and_are_hashed(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    selection_path = tmp_path / "selection.json"
    causal_path = tmp_path / "causal.jsonl"
    summary_path.write_text("{}", encoding="utf-8")
    selection_path.write_text("[]", encoding="utf-8")
    causal_path.write_text("", encoding="utf-8")
    receipt = build_receipt(
        {
            "schema": "alina.copy_vault_cloud_window.v2",
            "collection_run_id": "run-1",
            "read_only": True,
            "real_execution": False,
            "live_fill_counts": {"vault": 0},
            "l2_frames": 0,
            "l2_diagnostics": {},
            "subscription_diagnostics": {},
        },
        summary_path=summary_path,
        selection_path=selection_path,
        causal_rows_path=causal_path,
        head_sha="a" * 40,
    )
    assert receipt["evidence_status"] == "UNMEASURABLE"
    assert receipt["observation"]["causal_row_count"] == 0
    assert receipt["observation"]["causal_rows_sha256"]
    assert "CAUSAL_ROW_LEVEL_AUDIT_NOT_PROVEN" in receipt["observation"]["missing_evidence"]


def test_proven_causal_rows_bind_a_safe_replay_receipt(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    selection_path = tmp_path / "selection.json"
    causal_path = tmp_path / "causal.jsonl"
    summary_path.write_text("{}", encoding="utf-8")
    selection_path.write_text("[]", encoding="utf-8")
    causal_path.write_text(
        json.dumps(
            {
                "source": "LIVE_WS",
                "isSnapshot": False,
                "ts_ms": 1_020,
                "received_at_ms": 1_025,
                "ack_received_at_ms": 1_010,
                "capture_epoch": "run:ws:1000",
                "post_ack": True,
                "coin": "BTC",
                "tid": 2,
                "stable_event_id": "event-1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    receipt = build_receipt(
        {
            "schema": "alina.copy_vault_cloud_window.v2",
            "collection_run_id": "run-1",
            "read_only": True,
            "real_execution": False,
            "live_fill_counts": {"vault": 1},
            "l2_frames": 1,
            "l2_diagnostics": {},
            "subscription_diagnostics": {},
        },
        summary_path=summary_path,
        selection_path=selection_path,
        causal_rows_path=causal_path,
        head_sha="a" * 40,
    )
    assert receipt["schema"] == "hypersmart.copy_vault_live_ws_causal_receipt.v1"
    assert receipt["evidence_status"] == "PROVEN"
    assert receipt["claims"]["causal_live_fill_rows"] == 1
    assert receipt["claims"]["snapshot_excluded_from_forward"] is True

