from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text() -> str:
    return (ROOT / "LANCER_OBJECTIF_4USD.cmd").read_text(encoding="utf-8", errors="ignore")


def test_launcher_uses_portable_python_and_canonical_runner():
    text = _text()
    assert "tools\\portable_env.cmd" in text
    assert '"%HYPERSMART_PYTHON%" "%~dp0tools\\run_economic_objective_campaigns.py"' in text
    assert "--root \"%~dp0.\"" in text


def test_launcher_forces_execution_off():
    text = _text()
    assert 'set "HL_ENABLE_MAINNET_EXECUTION=0"' in text
    assert 'set "HL_ENABLE_TESTNET_EXECUTION=0"' in text
    assert 'set "REAL_MAINNET_TRADING=false"' in text


def test_launcher_names_only_three_canonical_economic_families():
    text = _text()
    assert "Copy-Vault / Lead-Lag / Cross-Venue Dislocation v2" in text
    assert "+4 USD NET" in text
    assert "Carry" not in text
