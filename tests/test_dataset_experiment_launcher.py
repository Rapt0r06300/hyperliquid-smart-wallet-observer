from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text() -> str:
    return (ROOT / "PREPARER_EXPERIENCE_FULL_COLD.cmd").read_text(
        encoding="utf-8", errors="replace"
    )


def test_bouton_experience_reste_local_et_sans_execution_reelle() -> None:
    text = _text()
    assert "HL_ENABLE_MAINNET_EXECUTION=0" in text
    assert "HL_ENABLE_TESTNET_EXECUTION=0" in text
    assert "REAL_MAINNET_TRADING=false" in text
    assert "HYPERSMART_ANALYSIS_LOCAL_ONLY=1" in text
    assert "dataset_experiment_plan" in text
    assert "dataset_experiment_contract" in text
    assert "dataset_experiment_contract_verify" in text
    assert "dataset_bridge locate" in text
    assert "--download" not in text
    assert "/exchange" not in text.casefold()


def test_bouton_experience_transmet_les_criteres_sans_lancer_de_replay() -> None:
    text = _text()
    assert "--family" in text
    assert "--coin" in text
    assert "--metric" in text
    assert "--start-ms" in text
    assert "--end-ms" in text
    assert "--wallet" in text
    assert "ANALYSER_DONNEES_HYPERSMART" not in text
    assert "dataset_research_runner" not in text


def test_bouton_experience_quote_directement_le_workspace_et_evite_un_args_fragile() -> None:
    text = _text()
    assert '--root "%DATA_ROOT%"' in text
    assert 'set "ARGS=' not in text
    assert ':sans_periode' in text
    assert ':debut_seul' in text
    assert ':sans_debut' in text


def test_bouton_experience_ne_fabrique_un_contrat_que_si_le_plan_est_ready() -> None:
    text = _text()
    assert 'if "%RC%"=="0" goto :contrat' in text
    assert 'if "%RC%"=="3" (' in text
    assert "Aucun contrat de replay READY n'est fabrique" in text
    assert ':contrat' in text
    assert "CURRENT_REPLAY_INPUT_CONTRACT.md" in text


def test_bouton_experience_verifie_le_contrat_avant_de_declarer_ok() -> None:
    text = _text()
    verify_call = 'hl_observer.ops.dataset_experiment_contract_verify --root "%DATA_ROOT%"'
    assert verify_call in text
    assert 'set "VERIFY_RC=%ERRORLEVEL%"' in text
    assert 'if not "%VERIFY_RC%"=="0" (' in text
    assert "Le contrat existe mais ne correspond pas aux sources reelles" in text
    assert "CURRENT_REPLAY_INPUT_CONTRACT_VERIFICATION.md" in text
    assert text.index(verify_call) < text.index("[OK] Plan, contrat et verification des sources sont prets")
