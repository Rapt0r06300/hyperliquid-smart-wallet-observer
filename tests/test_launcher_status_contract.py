"""Contrats de propagation des codes du lanceur principal.

Ces tests restent statiques et sans démarrage de collecteur : ils empêchent le
`.cmd` de transformer une erreur réelle en succès apparent ou en retour opaque.
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CMD = (ROOT / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="strict")


def _block(label: str, next_label: str) -> str:
    start = CMD.index("\n" + label) + 1
    end = CMD.index("\n" + next_label, start)
    return CMD[start:end]


def test_unknown_subcommand_is_an_error_not_a_menu_success():
    dispatch = _block(":dispatch", ":cmd_menu")
    assert 'set "RC=64"' in dispatch
    assert dispatch.rstrip().endswith('goto :fin')


def test_audit_is_read_only_and_propagates_its_code():
    audit = _block(":cmd_audit", ":cmd_replay")
    assert "-m pip install" not in audit.lower()
    assert 'set "AUDIT_CODE=%ERRORLEVEL%"' in audit
    assert 'set "RC=%AUDIT_CODE%"' in audit


def test_status_and_collectors_propagate_codes():
    status = _block(":cmd_status", ":cmd_sante")
    core = _block(":cmd_collectors", ":cmd_collectors_harvest")
    maintenance = _block(":cmd_collectors_maintenance", ":cmd_collectors_research")
    research = _block(":cmd_collectors_research", ":cmd_collectors_all")
    assert 'set "RC=%ERRORLEVEL%"' in status
    assert 'set "RC=%ERRORLEVEL%"' in core
    assert 'set "RC=%ERRORLEVEL%"' in maintenance
    assert 'set "RC=%ERRORLEVEL%"' in research


def test_report_test_replay_reset_selftest_and_oos_propagate_codes():
    blocks = (
        _block(":cmd_report", ":cmd_test"),
        _block(":cmd_test", ":cmd_audit"),
        _block(":cmd_replay", ":cmd_moisson"),
        _block(":cmd_resetpaper", ":cmd_selftest"),
        _block(":cmd_selftest", "REM -------- AVANCES"),
        _block(":cmd_verifoos", ":oos_install"),
        _block(":oos_testnotif", ":cmd_github"),
    )
    assert all('set "RC=%ERRORLEVEL%"' in block for block in blocks)
    assert 'exit /b %ERRORLEVEL%' not in blocks[2]


def test_userfills_uses_authenticated_supervisor_without_global_process_kill():
    restart = _block(":cmd_ruserfills", ":cmd_collectors")
    stop = _block(":cmd_killuserfills", ":cmd_verifl2")
    for block in (restart, stop):
        assert "superviseur_collecteurs arreter-userfills" in block
        assert "Get-CimInstance Win32_Process" not in block
        assert "collecter_userfills_vaults.py*" not in block
    assert 'set "RC_USERFILLS=%ERRORLEVEL%"' in restart
    assert 'set "RC=%ERRORLEVEL%"' in restart
    assert 'set "RC=%ERRORLEVEL%"' in stop


def test_moisson_stop_uses_root_bounded_supervisor_not_window_titles():
    block = _block(":moisson_stop", ":cmd_verifoos")
    assert "superviseur_collecteurs arreter-moisson" in block
    assert "WINDOWTITLE" not in block
    assert "taskkill" not in block.lower()
    assert 'set "RC_MOISSON=%ERRORLEVEL%"' in block
