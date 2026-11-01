from __future__ import annotations

import pytest

from tools import run_copy_vault_regressions as runner
from tools.verify_copy_vault_tasklist import _read_receipts


def test_executable_has_only_current_existing_downstream_suites() -> None:
    selected = runner.select_tests([
        "src/hl_observer/backtesting/copy_vault_executable.py",
    ])

    assert selected == sorted(runner.COPY_VAULT_EXECUTABLE_SUITES)
    assert all((runner.ROOT / path).is_file() for path in selected)


def test_local_lab_and_pipeline_have_explicit_downstream_suites() -> None:
    local_lab = runner.select_tests([
        "src/hl_observer/backtesting/copy_vault_local_lab.py",
    ])
    pipeline = runner.select_tests(["tools/pipeline_copie_reel.py"])

    assert local_lab == sorted(runner.COPY_VAULT_LOCAL_LAB_SUITES)
    assert pipeline == sorted(runner.COPY_VAULT_PIPELINE_SUITES)


def test_copy_vault_evidence_tools_have_explicit_downstream_suites() -> None:
    expected = sorted({
        *runner.COPY_VAULT_EVIDENCE_SUITES,
    })
    selected = runner.select_tests([
        "tools/audit_live_ws_causal_capture.py",
        "tools/build_copy_vault_hosted_receipt.py",
        "tools/build_copy_vault_restoration_evidence.py",
        "tools/inventory_copy_vault_evidence.py",
        "tools/verify_copy_vault_closure_matrix.py",
        "tools/verify_copy_vault_causal_receipt.py",
        "tools/verify_copy_vault_snapshot_contract.py",
        "tools/verify_copy_vault_tasklist.py",
    ])

    assert selected == expected


def test_unknown_critical_module_fails_closed() -> None:
    with pytest.raises(ValueError, match="no regression mapping"):
        runner.select_tests(["src/hl_observer/backtesting/future_engine.py"])


def test_unrelated_document_does_not_schedule_economic_tests() -> None:
    assert runner.select_tests(["docs/README.md"]) == []


def test_missing_mapped_suite_fails_closed(monkeypatch) -> None:
    monkeypatch.setitem(
        runner.MODULE_TESTS,
        "src/hl_observer/backtesting/fake.py",
        ("tests/test_does_not_exist.py",),
    )

    with pytest.raises(ValueError, match="mapped regression suite"):
        runner.select_tests(["src/hl_observer/backtesting/fake.py"])


def test_unmapped_workflow_change_fails_closed() -> None:
    with pytest.raises(ValueError, match="no regression mapping"):
        runner.select_tests([".github/workflows/new-copy-vault-gate.yml"])


def test_changed_paths_includes_workflows(monkeypatch) -> None:
    class Result:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return Result(".github/workflows/copy-vault.yml\n")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner.changed_paths() == [".github/workflows/copy-vault.yml"]
    assert calls[1][-1] == ".github/workflows"


def test_tasklist_reader_includes_append_only_exact_sha_receipts(tmp_path) -> None:
    (tmp_path / "H-T95.json").write_text(
        '[{"head_sha":"old","evidence_status":"UNMEASURABLE"}]',
        encoding="utf-8",
    )
    (tmp_path / "H-T95-restoration-current-newsha-r1.json").write_text(
        '[{"head_sha":"newsha","evidence_status":"VERIFIED"}]',
        encoding="utf-8",
    )
    (tmp_path / "H-T95-restoration-current-newsha-r2.json").write_text(
        '{"head_sha":"newsha-2","evidence_status":"UNMEASURABLE"}',
        encoding="utf-8",
    )

    receipts = _read_receipts(tmp_path)

    assert receipts["H-T95"] == [
        {"head_sha": "old", "evidence_status": "UNMEASURABLE"},
        {"head_sha": "newsha", "evidence_status": "VERIFIED"},
        {"head_sha": "newsha-2", "evidence_status": "UNMEASURABLE"},
    ]
