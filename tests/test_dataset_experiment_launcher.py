from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bouton_experience_reste_local_et_sans_execution_reelle() -> None:
    text = (ROOT / "PREPARER_EXPERIENCE_FULL_COLD.cmd").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "HL_ENABLE_MAINNET_EXECUTION=0" in text
    assert "HL_ENABLE_TESTNET_EXECUTION=0" in text
    assert "REAL_MAINNET_TRADING=false" in text
    assert "HYPERSMART_ANALYSIS_LOCAL_ONLY=1" in text
    assert "dataset_experiment_plan" in text
    assert "dataset_bridge locate" in text
    assert "--download" not in text
    assert "/exchange" not in text.casefold()


def test_bouton_experience_transmet_les_criteres_sans_lancer_de_replay() -> None:
    text = (ROOT / "PREPARER_EXPERIENCE_FULL_COLD.cmd").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "--family" in text
    assert "--coin" in text
    assert "--metric" in text
    assert "--start-ms" in text
    assert "--end-ms" in text
    assert "--wallet" in text
    assert "ANALYSER_DONNEES_HYPERSMART" not in text
    assert "dataset_research_runner" not in text
