from __future__ import annotations

import copy
import json
from pathlib import Path

import tools.alina_quant_lab_console as lab
from hl_observer.backtesting.copy_vault_v21_frozen import _verified_freeze
from hl_observer.simulation.economic_freeze_registry import parameter_hash
from tools.alina_quant_lab_console import (
    _pytest_counts,
    _run_group,
    _test_groups,
    assess_physical_freeze,
)

ROOT = Path(__file__).resolve().parents[1]
FREEZE_PATH = ROOT / "runtime" / "codex_research" / "COPY_V21_PHYSICAL_FREEZE.json"


def test_lab_reports_the_existing_over_limit_freeze_without_modifying_it() -> None:
    before = FREEZE_PATH.read_bytes()

    result = assess_physical_freeze(FREEZE_PATH)

    assert result["status"] == "REJECTED"
    assert result["reason"] == "COPY_V21_PAPER_GROSS_EXPOSURE_LIMIT_EXCEEDED"
    assert FREEZE_PATH.read_bytes() == before


def test_lab_recognizes_a_valid_physical_freeze_without_promoting_it(
    tmp_path: Path,
) -> None:
    source = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    payload = copy.deepcopy(source)
    params = payload["freeze"]["parameters"]
    params["core_notional_usd"] = 200.0
    payload["freeze"]["parameters_sha256"] = parameter_hash(params)
    target = tmp_path / "freeze.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    result = assess_physical_freeze(target)

    assert _verified_freeze(payload)["parameters"]["core_notional_usd"] == 200.0
    assert result["status"] == "VALID_PHYSICAL_FREEZE"
    assert result["core_notional_usd"] == 200.0


def test_lab_extracts_independent_pytest_summary_counts() -> None:
    counts = _pytest_counts("= 7 passed, 2 failed, 1 skipped in 3.2s =")

    assert counts["passed"] == 7
    assert counts["failed"] == 2
    assert counts["skipped"] == 1
    assert counts["errors"] == 0


def test_lab_counts_a_single_collection_error() -> None:
    counts = _pytest_counts("1 error, 3 passed in 1.2s")

    assert counts["errors"] == 1
    assert counts["passed"] == 3


def test_lab_fails_closed_when_a_required_test_group_is_empty(tmp_path: Path) -> None:
    result = _run_group("groupe obligatoire", [], tmp_path / "missing.log")

    assert result["status"] == "FAIL"
    assert result["return_code"] != 0


def test_lab_covers_copy_vault_scope_paper_and_readiness_boundaries() -> None:
    groups = _test_groups()
    selected = {path for _name, paths in groups for path in paths}

    assert {
        "tests/test_paper_canonique.py",
        "tests/test_strategy_readiness.py",
        "tests/test_readme_scope_coherence.py",
    } <= selected
    assert all(paths for _name, paths in groups)
    assert sum(len(paths) for _name, paths in groups) == len(selected)


def test_lab_uses_at_most_65_percent_of_logical_cpus(monkeypatch) -> None:
    monkeypatch.setenv("ALINA_QUANT_CPU_PERCENT", "65")
    monkeypatch.setattr(lab.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(
        lab.importlib.util,
        "find_spec",
        lambda name: object() if name == "xdist" else None,
    )

    assert lab._pytest_parallel_args(20) == ["-n", "10", "--dist", "loadfile"]


def test_lab_falls_back_to_serial_when_xdist_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(lab.importlib.util, "find_spec", lambda _name: None)

    assert lab._pytest_parallel_args(20) == []


def test_copy_vault_lab_launcher_checks_complete_test_runtime() -> None:
    launcher = (ROOT / "LANCER_LAB_QUANT_COPY_VAULT.cmd").read_text(
        encoding="utf-8"
    )

    assert "tools\\python\\python.exe" in launcher
    assert "import pytest, typer" in launcher
    assert 'set "ALINA_QUANT_CPU_PERCENT=65"' in launcher
    assert '"%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% -c' in launcher


def test_lab_writes_complete_reports_when_a_group_is_interrupted(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("ALINA_QUANT_NO_OPEN", "1")
    monkeypatch.setattr(lab, "ROOT", tmp_path)
    monkeypatch.setattr(lab, "_restore_processes", lambda: [])
    monkeypatch.setattr(lab, "_test_groups", lambda: [("interrupted", ["test_x.py"])])
    monkeypatch.setattr(
        lab,
        "_run_group",
        lambda *_args, **_kwargs: {
            "name": "interrupted",
            "status": "INTERRUPTED",
            "return_code": 130,
            "counts": lab._pytest_counts(""),
            "seconds": 1.0,
            "cpu_seconds": 0.1,
            "peak_working_set_bytes": 1,
            "log": "interrupted.log",
        },
    )

    assert lab.run_lab() == 130
    reports = list((tmp_path / "runtime" / "reports" / "copy_vault_quant_lab").glob("*"))
    assert len(reports) == 1
    result = json.loads((reports[0] / "resultat.json").read_text(encoding="utf-8"))
    assert result["status"] == "INTERRUPTED"
    assert "**INTERRUPTED**" in (reports[0] / "RAPPORT.md").read_text(encoding="utf-8")
    dashboard = (reports[0] / "RAPPORT.html").read_text(encoding="utf-8")
    assert "Laboratoire CopyVault" in dashboard
    assert "INTERRUPTED" in dashboard
    assert "Meilleure stratégie prouvée" in dashboard
