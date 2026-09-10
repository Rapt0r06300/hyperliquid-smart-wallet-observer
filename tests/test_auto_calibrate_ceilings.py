from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "auto_calibrate_ceilings.py"
SPEC = importlib.util.spec_from_file_location("auto_calibrate_ceilings", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
auto_calibrate_ceilings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auto_calibrate_ceilings)


def test_check_ceilings_detects_only_improvement_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auto_calibrate_ceilings, "_read_python_var", lambda _path, _name: 10)

    state = {
        "declared_debt": 9,
        "testes_non_branches": 19,
        "orphelins": 10,
    }

    candidates = auto_calibrate_ceilings.check_ceilings(state)

    assert [(item.name, item.current_value, item.ceiling) for item in candidates] == [
        ("PLAFOND_DETTE", 9, 10),
    ]


def test_auto_calibrate_refuses_to_raise_a_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard_file = tmp_path / "guard.py"
    guard_file.write_text("LIMIT = 10\n", encoding="utf-8")
    regression = auto_calibrate_ceilings.Ceiling(
        name="LIMIT",
        current_value=11,
        ceiling=10,
        file_path=guard_file,
        variable_name="LIMIT",
    )
    monkeypatch.setattr(auto_calibrate_ceilings, "check_ceilings", lambda _state: [regression])

    def _git_must_not_run(*_args, **_kwargs):
        pytest.fail("regressions must fail closed before any git command")

    monkeypatch.setattr(auto_calibrate_ceilings.subprocess, "run", _git_must_not_run)

    result = auto_calibrate_ceilings.auto_calibrate(
        {"fiable": True, "declared_debt": 0, "testes_non_branches": 0, "orphelins": 0},
        commit=True,
    )

    assert result == 1
    assert guard_file.read_text(encoding="utf-8") == "LIMIT = 10\n"
