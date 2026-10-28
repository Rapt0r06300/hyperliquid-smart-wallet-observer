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


def test_pre_run_101_200_gate_avoids_full_tree_status_timeout() -> None:
    workflow = (ROOT / ".github" / "workflows" / "pre-run-101-200.yml").read_text(
        encoding="utf-8"
    )
    block = workflow.split("- name: Gate initial exact HEAD securite et couverture", 1)[1].split(
        "- uses: actions/setup-python", 1
    )[0]
    assert "git diff --quiet HEAD -- src tests tools .github" in block
    assert "--require-clean-git" not in block
    assert "git status" in block  # explanatory comment documents the avoided slow probe
    assert "pre_run_guard_101_200" in block
