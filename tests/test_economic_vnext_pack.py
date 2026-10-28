from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.backtesting import economic_vnext_pack as module


def _make_pack_deterministic(monkeypatch) -> None:
    monkeypatch.setattr(module, "require_runnable_copy_vault_hypothesis", lambda _mechanism: {"id": "copy-vault-test"})
    monkeypatch.setattr(module, "copy_vault_hypothesis_ledger", lambda: [])
    monkeypatch.setattr(module, "_load_copy_raw", lambda _root: None)
    monkeypatch.setattr(module, "evaluate_copy_vault_vnext_integrity", lambda _raw: {"eligible": False, "reasons": ["NO_RAW_REPORT"]})

    def gate(candidate, integrity):
        assert integrity["eligible"] is False
        return {
            **candidate,
            "selection_eligible": False,
            "physical_freeze_allowed": False,
            "heldout_evaluated": False,
        }

    monkeypatch.setattr(module, "gate_copy_vault_candidate", gate)


def test_vnext_pack_only_runs_copy_vault_and_never_reads_disabled_sources(
    tmp_path: Path, monkeypatch
) -> None:
    _make_pack_deterministic(monkeypatch)
    forbidden_source = tmp_path / "must-not-be-opened.jsonl"

    result = module.run_economic_vnext_pack(tmp_path, lead_sources=[forbidden_source])

    assert result["active_family"] == "copy_vault"
    assert set(result["families"]) == {"copy_vault"}
    assert result["disabled_families"] == {
        "lead_lag": "DISABLED_BY_SCOPE",
        "cross_venue_dislocation": "DISABLED_BY_SCOPE",
    }
    assert result["ignored_lead_source_count"] == 1
    assert result["lead_source_paths_read"] is False
    assert result["families"]["copy_vault"]["status"] == "COPY_RAW_REPORT_MISSING"
    assert result["families"]["copy_vault"]["selection_eligible"] is False
    assert result["families"]["copy_vault"]["physical_freeze_allowed"] is False
    assert all(name.startswith("copy_vault") for name in result["reports"])
    assert not any("lead_lag" in name or "cross_venue" in name for name in result["reports"])
    assert not forbidden_source.exists()
    assert (tmp_path / result["summary_path"]).is_file()

    summary = json.loads((tmp_path / result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["families"].keys() == {"copy_vault"}
    assert summary["lead_source_paths_read"] is False

    report_dir = tmp_path / module.REPORT_DIR
    written_names = {path.name for path in report_dir.glob("*.json")}
    assert all(
        name.startswith("copy_vault") or name == "VNext_SUMMARY.json"
        for name in written_names
    )
    assert "VNext_SUMMARY.json" in written_names


def test_vnext_pack_fails_closed_before_reads_or_writes_when_scope_rejects_copy_vault(
    tmp_path: Path, monkeypatch
) -> None:
    reads: list[Path] = []
    monkeypatch.setattr(module, "require_active_strategy", lambda _family: (_ for _ in ()).throw(ValueError("DISABLED_BY_SCOPE:copy_vault")))
    monkeypatch.setattr(module, "_load_copy_raw", lambda root: reads.append(Path(root)))

    with pytest.raises(ValueError, match="DISABLED_BY_SCOPE:copy_vault"):
        module.run_economic_vnext_pack(tmp_path, lead_sources=[])

    assert reads == []
    assert not (tmp_path / module.REPORT_DIR).exists()


def test_vnext_pack_records_no_certification_or_heldout_claims(tmp_path: Path, monkeypatch) -> None:
    _make_pack_deterministic(monkeypatch)

    result = module.run_economic_vnext_pack(tmp_path, lead_sources=[])

    assert result["certification_status"] == "TRAIN_ONLY_NOT_CERTIFIED"
    assert result["canonical_campaigns_mutated"] is False
    assert result["heldout_evaluated"] is False
    assert result["post_freeze_oos_consumed"] is False
    assert result["freeze_hash"] is None
    assert result["real_execution"] is False
    assert result["paper_read_only"] is True
    assert all(
        details["heldout_evaluated"] is False
        for details in result["research_variants"].values()
    )
