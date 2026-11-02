from __future__ import annotations

from pathlib import Path

from tools.build_copy_vault_hosted_soak_receipt import build_receipt


def _soak() -> dict[str, object]:
    common = {
        "input_count": 10,
        "input_sha256": "a" * 64,
        "accepted_count": 9,
        "accepted_sha256": "b" * 64,
        "interrupted": False,
        "status": "COMPLETE",
    }
    interrupted = dict(common)
    interrupted.update({"accepted_count": 3, "accepted_sha256": "c" * 64, "interrupted": True, "status": "CONTINUATION_REQUIRED"})
    return {
        "status": "PASS",
        "same_result_after_resume": True,
        "paper_read_only": True,
        "real_execution": False,
        "interrupted": interrupted,
        "resumed": dict(common),
        "continuous": dict(common),
    }


def test_hosted_soak_receipt_requires_and_records_exact_provenance(tmp_path: Path) -> None:
    source = tmp_path / "soak.json"
    source.write_text("{}\n", encoding="utf-8")
    receipt = build_receipt(
        _soak(),
        soak_path=source,
        head_sha="a" * 40,
        run_id="123",
        artifact_id="456",
        artifact_digest="sha256:" + "d" * 64,
    )
    assert receipt["evidence_status"] == "VERIFIED"
    assert receipt["claims"]["checkpoint_resume_proven"] is True
    assert receipt["full_dataset_certified"] is False
    assert len(receipt["receipt_sha256"]) == 64
