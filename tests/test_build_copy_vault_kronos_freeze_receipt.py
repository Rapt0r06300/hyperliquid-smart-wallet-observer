from __future__ import annotations

from pathlib import Path

from tools.build_copy_vault_kronos_freeze_receipt import build_receipt


def test_historical_kronos_metadata_cannot_become_current_closure(tmp_path: Path) -> None:
    source = tmp_path / "historical.json"
    source.write_text("[]", encoding="utf-8")
    receipt = build_receipt(
        [{
            "head_sha": "b" * 40,
            "claims": {
                "repo_model_tokenizer_license_frozen": True,
                "missing_fields_not_zeroed": True,
                "unresolved": ["historical source has no cutoff"],
            },
        }],
        source_path=source,
        head_sha="a" * 40,
    )
    assert receipt["evidence_status"] == "UNMEASURABLE"
    assert receipt["decision"] == "NO_GO"
    assert receipt["source"]["historical_head_sha"] == "b" * 40
    assert receipt["claims"]["post_training_cutoff"] is False
    assert "AUTHORITATIVE_POST_TRAINING_CUTOFF_MISSING" in receipt["missing_evidence"]
