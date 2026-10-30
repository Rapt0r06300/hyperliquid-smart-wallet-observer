from __future__ import annotations

import pytest

from tools import run_copy_vault_regressions as runner


def test_executable_has_only_current_existing_downstream_suites() -> None:
    selected = runner.select_tests([
        "src/hl_observer/backtesting/copy_vault_executable.py",
    ])

    assert selected == sorted(runner.COPY_VAULT_EXECUTABLE_SUITES)
    assert all((runner.ROOT / path).is_file() for path in selected)


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
