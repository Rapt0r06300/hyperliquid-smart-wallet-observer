"""[ANALYSER items 2,5,6,7] Durcissement du .cmd maitre : Python portable exclusif (aucun repli py -3),
ERRORLEVEL verifie apres chaque commande critique, analyse scopee a la session selectionnee, propagation
du code de sortie, et JAMAIS d'ouverture d'un ancien rapport si le run courant echoue.
"""
from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
CMD = (RACINE / "ANALYSER_BACKTESTS_REPLAYS.cmd").read_text(encoding="utf-8", errors="ignore")


def test_python_portable_exclusif_sans_repli_py3():
    assert "%HYPERSMART_PYTHON%" in CMD                       # item 6 : Python portable exclusif
    assert "py -3" not in CMD                                 # item 6 : plus de repli qui contourne le portable
    assert "where py" not in CMD


def test_errorlevel_de_portable_env_verifie_immediatement():
    i_call = CMD.index('call "%~dp0tools\\portable_env.cmd"')
    i_check = CMD.index("if errorlevel 1", i_call)
    # le check suit immediatement l'appel (pas d'autre commande critique entre les deux).
    entre = CMD[i_call:i_check]
    assert "hl_observer" not in entre and i_check - i_call < 200


def test_analyse_scopee_a_la_session_selectionnee():
    assert "--emit-run-id" in CMD                             # item 2 : recupere le run_id selectionne
    assert "--session-dir" in CMD                             # item 2 : lab scope a CETTE session
    i_sel = CMD.index("analyser_session")
    i_lab = CMD.index("lab_alpha", i_sel)
    assert i_sel < i_lab                                      # selection AVANT analyse
    assert "SESSION_DIR=%~dp0runtime\\data\\sessions\\%RUN_ID%" in CMD


def test_fenetre_ram_bornable():
    assert "--max-ram-events" in CMD                          # item 7 : replay a fenetre RAM bornable


def test_seuil_fraicheur_configurable():
    # item 11 : seuil d'age configurable, defaut fini (48 h), passe a analyser_session, override 0 = illimite.
    assert "HYPERSMART_AGE_MAX_S" in CMD
    assert 'set "HYPERSMART_AGE_MAX_S=172800"' in CMD         # defaut 48 h (pas d'infini par defaut)
    assert "--age-max-s %HYPERSMART_AGE_MAX_S%" in CMD        # transmis au selecteur de session
    i_def = CMD.index("HYPERSMART_AGE_MAX_S=172800")
    i_use = CMD.index("--age-max-s %HYPERSMART_AGE_MAX_S%")
    assert i_def < i_use                                      # defaut pose AVANT usage
    # 0 (ou vide) = pas de limite d'age : l'option n'est alors pas passee.
    assert 'if not "%HYPERSMART_AGE_MAX_S%"=="0" set "OPT_AGE=--age-max-s %HYPERSMART_AGE_MAX_S%"' in CMD


def test_propagation_code_sortie_et_pas_de_vieux_rapport_sur_echec():
    assert "set \"RC=%ERRORLEVEL%\"" in CMD
    # si le run courant echoue -> on N'OUVRE PAS un ancien rapport, on propage RC.
    i_fail = CMD.index('if not "%RC%"=="0"')
    i_open = CMD.index('start "" "%RAP%"')
    assert i_fail < i_open                                    # le garde-fou d'echec est AVANT l'ouverture
    assert CMD.rstrip().endswith("exit /b %RC%")              # code de sortie propage jusqu'au bout
