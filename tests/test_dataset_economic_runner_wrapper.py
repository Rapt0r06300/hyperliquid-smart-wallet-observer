from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "tools" / "run_dataset_economic_campaigns.py"
ANALYSER = ROOT / "ANALYSER_DONNEES_HYPERSMART.cmd"


def test_wrapper_full_cold_installe_les_adaptateurs_et_la_provenance_complete() -> None:
    text = WRAPPER.read_text(encoding="utf-8", errors="replace")
    assert "install_copy_vault_adapter" in text
    assert "install_cross_venue_adapter" in text
    assert "write_economic_source_coverage" in text
    assert "canonical.dataset_provenance = dataset_provenance" in text
    assert "load_family_source_paths(data_root, \"lead_lag\")" in text
    assert "start_collection=False" in text
    assert "--no-start-collection est obligatoire" in text
    assert "/exchange" not in text.casefold()


def test_analyser_utilise_wrapper_seulement_pour_une_suite_reproductible() -> None:
    text = ANALYSER.read_text(encoding="utf-8", errors="replace")
    assert 'set "ECONOMIC_RUNNER=%~dp0tools\\run_economic_objective_campaigns.py"' in text
    assert 'set "ECONOMIC_RUNNER=%~dp0tools\\run_dataset_economic_campaigns.py"' in text
    assert 'if "%DATASET_SUITE%"==""' in text
    assert "SOURCE_CONSUMPTION_COVERAGE.md" in text
    assert "HL_ENABLE_MAINNET_EXECUTION=0" in text
    assert "HL_ENABLE_TESTNET_EXECUTION=0" in text
