from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "tools" / "run_economic_objective_campaigns.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("economic_runner_scope_test", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runner_fails_closed_before_any_io_if_scope_is_widened(monkeypatch, tmp_path: Path) -> None:
    runner = _load_runner()
    monkeypatch.setattr(runner, "assert_execution_disabled", lambda: None)
    monkeypatch.setattr(runner, "require_active_strategy", lambda family: family)
    monkeypatch.setattr(
        runner,
        "active_strategy_families",
        lambda: frozenset({"copy_vault", "lead_lag"}),
    )
    monkeypatch.setattr(
        runner,
        "_environment_provenance",
        lambda _root: pytest.fail("scope must be checked before repository/data reads"),
    )

    with pytest.raises(RuntimeError, match="COPY_VAULT_ONLY_SCOPE_REQUIRED"):
        runner.run_campaigns(tmp_path)

    assert list(tmp_path.iterdir()) == []
