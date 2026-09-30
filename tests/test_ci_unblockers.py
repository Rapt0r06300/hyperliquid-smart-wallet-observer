from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dataset_workflow_installs_declared_runtime_dependencies() -> None:
    workflow = (ROOT / ".github" / "workflows" / "donnees-hypersmart.yml").read_text(
        encoding="utf-8"
    )
    assert workflow.count('python -m pip install -e ".[dev]"') == 2
    assert "python -m pip install -e . --no-deps" not in workflow


def test_pre_run_clean_gate_is_shell_level_before_and_after_python_probe() -> None:
    workflow = (ROOT / ".github" / "workflows" / "pre-run-001-100.yml").read_text(
        encoding="utf-8"
    )
    block = workflow.split("- name: Gate initial sur checkout exact et propre", 1)[1].split(
        "- uses: actions/setup-python", 1
    )[0]
    clean_cmd = "git status --porcelain=v1 --untracked-files=all"
    probe = "python3 -m hl_observer.ops.pre_run_guard_001_100"
    assert block.count(clean_cmd) == 2
    assert "--require-clean-git" not in block
    assert block.index(clean_cmd) < block.index(probe) < block.rindex(clean_cmd)
