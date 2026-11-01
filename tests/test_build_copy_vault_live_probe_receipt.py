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
    assert receipt["real_execution"] is False
    assert receipt["claims"]["causal_post_ack_fill_proven"] is False
    assert receipt["observation"]["live_fill_total_reported"] == 4
    assert "ROW_LEVEL_CAUSAL_LIVE_WS_RECEIPT_MISSING" in receipt["observation"]["missing_evidence"]

