from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8", errors="replace")


def test_lanceur_176go_garde_toute_execution_coupee() -> None:
    text = _read("LANCER_REPLAY_176GO.cmd")
    assert "HL_ENABLE_MAINNET_EXECUTION=0" in text
    assert "HL_ENABLE_TESTNET_EXECUTION=0" in text
    assert "REAL_MAINNET_TRADING=false" in text
    assert "--preset economic-core" in text
    assert "--heartbeat-seconds 1" in text
    assert "/exchange" not in text.casefold()


def test_analyse_full_cold_ne_collecte_pas_et_termine_par_audit_de_raccordement() -> None:
    text = _read("ANALYSER_DONNEES_HYPERSMART.cmd")
    assert "HL_ENABLE_MAINNET_EXECUTION=0" in text
    assert "HL_ENABLE_TESTNET_EXECUTION=0" in text
    assert "REAL_MAINNET_TRADING=false" in text
    assert "--no-start-collection" in text
    assert "dataset_result_export" in text
    assert "dataset_connection_audit" in text
    assert "DATASET_CONNECTION_AUDIT.md" in text
    assert "/exchange" not in text.casefold()


def test_menu_donnees_demande_oui_avant_gros_telechargement() -> None:
    text = _read("PREPARER_DONNEES_HYPERSMART.cmd")
    assert 'set /p "CONFIRM=Ecris OUI' in text
    assert '--preset economic-core --download' in text
