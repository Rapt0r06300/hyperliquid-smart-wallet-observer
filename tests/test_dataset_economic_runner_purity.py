from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools" / "run_dataset_economic_campaigns.py"


def test_dataset_economic_runner_ne_monkeypatch_plus_le_module_canonique() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    assert "canonical._tool =" not in text
    assert "canonical.dataset_provenance =" not in text
    assert "_isolated_run_campaigns" in text
    assert "FunctionType" in text
    assert 'environment["_tool"] = tool_loader' in text
    assert 'environment["dataset_provenance"] = provenance_builder' in text
    assert 'result["canonical_globals_mutated"] = False' in text
