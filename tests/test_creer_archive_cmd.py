"""[PORTABILITE item 20] Durcissement du .cmd maitre d'archive : Python portable exclusif, ERRORLEVEL
de portable_env verifie tout de suite, ancrage %~dp0, tentative de cloture AVANT construction, appel
au module archive_portable, et propagation du code de sortie. Contrat teste sur le TEXTE (0 reseau).
"""
from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
CMD = (RACINE / "CREER_ARCHIVE_PORTABLE.cmd").read_text(encoding="utf-8", errors="ignore")


def test_python_portable_exclusif():
    assert "%HYPERSMART_PYTHON%" in CMD
    assert "py -3" not in CMD and "where py" not in CMD          # aucun repli qui contourne le portable


def test_ancre_sur_dp0():
    assert 'cd /d "%~dp0"' in CMD
    assert 'call "%~dp0tools\\portable_env.cmd"' in CMD


def test_errorlevel_portable_env_verifie_immediatement():
    i_call = CMD.index('call "%~dp0tools\\portable_env.cmd"')
    i_check = CMD.index("if errorlevel 1", i_call)
    entre = CMD[i_call:i_check]
    assert "hl_observer" not in entre and i_check - i_call < 200  # rien de critique entre appel et check


def test_cloture_avant_construction():
    i_clot = CMD.index("session_harvest cloturer")
    i_arch = CMD.index("hl_observer.ops.archive_portable")
    assert i_clot < i_arch                                        # item 20.2 : cloturer AVANT d'archiver


def test_appelle_le_module_archive():
    assert "-m hl_observer.ops.archive_portable" in CMD
    assert "--racine" in CMD


def test_securite_paper_strict():
    assert 'set "HL_ENABLE_MAINNET_EXECUTION=0"' in CMD
    assert 'set "REAL_MAINNET_TRADING=false"' in CMD


def test_propagation_code_sortie():
    assert 'set "RC=%ERRORLEVEL%"' in CMD
    assert "exit /b %RC%" in CMD
    # les codes de refus/echec sont expliques a l'utilisateur.
    assert '"%RC%"=="5"' in CMD and '"%RC%"=="4"' in CMD
