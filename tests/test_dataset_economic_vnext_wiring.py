from __future__ import annotations

from pathlib import Path


def test_dataset_full_cold_runs_copy_vault_only_under_active_scope() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "tools" / "run_dataset_economic_campaigns.py").read_text(encoding="utf-8")

    assert "from hl_observer.backtesting.copy_vault_v21_frozen import evaluate_frozen_v21" in text
    assert "from hl_observer.backtesting.economic_vnext_pack import run_economic_vnext_pack" not in text
    assert "copy_vault_only=True" in text
    assert '"status": "DISABLED_BY_SCOPE"' in text
    assert 'result["vnext_research"] = vnext_research' in text
    assert 'result["copy_vault_v21_frozen"] = copy_v21' in text
    assert "COPY_V21_PHYSICAL_FREEZE.json" in text
    assert text.index("result = isolated_run(") < text.index('"status": "DISABLED_BY_SCOPE"')
    assert 'result["canonical_globals_mutated"] = False' in text
    assert 'result["real_execution"] = False' in text
