from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_labo_180go_est_paper_only_demande_confirmation_et_expose_sqlite() -> None:
    text = (ROOT / "LANCER_LABO_180GO.cmd").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "HL_ENABLE_MAINNET_EXECUTION=0" in text
    assert "HL_ENABLE_TESTNET_EXECUTION=0" in text
    assert "REAL_MAINNET_TRADING=false" in text
    assert "plan-all" in text
    assert '--suite "%SUITE%"' in text
    assert '--heartbeat-seconds 1' in text
    assert 'set /p "CONFIRM=Ecris OUI' in text
    assert 'set /p "CONFIRM_ALL=Ecris TOUT' in text
    assert "sqlite-core" in text
    assert "sqlite-all-safe" in text
    assert "dataset_research_runner" in text
    assert "--full" in text
    assert "bases SQLite marquees corrompues sont exclues" in text
    assert "/exchange" not in text.casefold()


def test_analyse_peut_cibler_un_workspace_de_suite() -> None:
    text = (ROOT / "ANALYSER_DONNEES_HYPERSMART.cmd").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "dataset_bridge locate" in text
    assert "--suite" in text
    assert "--no-start-collection" in text
