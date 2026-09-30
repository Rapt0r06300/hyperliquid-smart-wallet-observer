from __future__ import annotations

from pathlib import Path


def test_dataset_full_cold_cable_vnext_apres_la_campagne_canonique() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "tools" / "run_dataset_economic_campaigns.py").read_text(encoding="utf-8")

    assert "from hl_observer.backtesting.economic_vnext_pack import run_economic_vnext_pack" in text
    assert "vnext_research = run_economic_vnext_pack(data_root, lead_sources=lead_sources)" in text
    assert 'result["vnext_research"] = vnext_research' in text
    assert text.index("result = isolated_run(") < text.index("vnext_research = run_economic_vnext_pack")
    assert 'result["canonical_globals_mutated"] = False' in text
    assert 'result["real_execution"] = False' in text
