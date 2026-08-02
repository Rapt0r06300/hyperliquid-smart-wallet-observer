"""[LANCER items 9,10] Durcissement du .cmd maitre : Python portable exclusif (aucun `python` nu),
codes de sortie propages de bout en bout (stop_impl rend le premier code non nul ; :fin propage %RC% ;
jamais un exit /b 0 systematique sur le chemin autopilot). Verifie sur le TEXTE du .cmd. 0 reseau.
"""
from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
CMD = (RACINE / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="ignore")


def test_aucun_appel_python_nu():
    # item 10 : aucune ligne de commande ne lance `python ` nu (toujours %HYPERSMART_PYTHON%).
    for ln in CMD.splitlines():
        s = ln.lstrip()
        if s.upper().startswith("REM"):
            continue
        assert not s.startswith("python "), "appel python nu: %r" % ln
        assert 'start "" /b python ' not in ln, "start python nu: %r" % ln
    assert "%HYPERSMART_PYTHON%" in CMD


def test_portable_env_echec_est_non_nul():
    # item 10 : un echec de portable_env reste non nul jusqu'a la sortie.
    i = CMD.index('call "%~dp0tools\\portable_env.cmd"')
    bloc = CMD[i:i + 400]
    assert 'set "RC=30"' in bloc and "if errorlevel 1" in bloc


def test_stop_impl_capture_les_deux_codes_et_rend_le_premier_non_nul():
    i = CMD.index("\n:stop_impl\n")                       # le LABEL, pas une reference `call`
    bloc = CMD[i:CMD.index("exit /b %RC_STOP%", i) + 20]
    assert 'set "RC_SUP=%ERRORLEVEL%"' in bloc            # code du superviseur capture
    assert 'set "RC_CLO=%ERRORLEVEL%"' in bloc            # code de la cloture capture
    assert "exit /b %RC_STOP%" in bloc                    # rend le premier non nul, jamais exit /b 0
    # aucune LIGNE DE COMMANDE `exit /b 0` (les commentaires REM qui la mentionnent sont ignores).
    for ln in bloc.splitlines():
        s = ln.strip()
        if s.upper().startswith("REM"):
            continue
        assert s != "exit /b 0", "stop_impl ne doit jamais faire exit /b 0"


def test_fin_propage_le_code_reel():
    assert "endlocal & exit /b %RC%" in CMD               # item 9 : :fin propage %RC%, pas un 0 fixe


def test_restart_ne_redemarre_pas_sur_arret_en_echec():
    i = CMD.index("\n:cmd_restart\n")                     # le LABEL, pas la ligne de dispatch
    bloc = CMD[i:i + 400]
    assert 'set "RC_STOP=%ERRORLEVEL%"' in bloc
    assert 'if not "%RC_STOP%"=="0"' in bloc              # arret en echec -> pas de restart silencieux


def test_moteur_et_arret_propagent_sur_le_chemin_autopilot():
    i = CMD.index("start_hypersmart_simulation.ps1")
    bloc = CMD[i:i + 700]
    assert 'set "RC_MOTEUR=%ERRORLEVEL%"' in bloc         # code du moteur PowerShell capture
    assert "call :stop_impl" in bloc and 'set "RC_STOP=%ERRORLEVEL%"' in bloc
