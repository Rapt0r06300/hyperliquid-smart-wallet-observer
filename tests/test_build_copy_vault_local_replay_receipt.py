from __future__ import annotations

from pathlib import Path

from tools.build_copy_vault_local_replay_receipt import build_receipt


def test_train_only_replay_cannot_become_oos_proof(tmp_path: Path) -> None:
    source = tmp_path / "trades.json"
    source.write_text("[]", encoding="utf-8")
    result = {
        "status": "COMPLETED_EXPLORATORY",
        "reason": "TRAIN_ONLY_PRESERVED_EXECUTABLE_TRADES_NO_HELDOUT_PROOF",
        "source_trade_count": 8,
        "source_distinct_days": 4,
        "trial_count": 73728,
        "economically_proven": False,
        "paper_read_only": True,
        "real_execution": False,
        "baseline": {"sample_count": 8},
        "oos": None,
        "forward": None,
        "report": None,
    }
    receipt = build_receipt(
        result,
        task_scope="H-T99",
        head_sha="a" * 40,
        source_path=source,
    )
    assert receipt["evidence_status"] == "UNMEASURABLE"
    assert receipt["decision"] == "NO_GO"
    assert receipt["kind"] == "economic_replay"
    assert receipt["replay"]["trial_count"] == 73728
    assert "OOS_FROZEN_REPLAY_MISSING" in receipt["missing_evidence"]
