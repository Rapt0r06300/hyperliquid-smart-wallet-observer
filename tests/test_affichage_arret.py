"""Garde-fou de l'arrêt des collecteurs (écran temps réel).

Le chemin d'arrêt ne doit JAMAIS tuer l'écran lui-même, le scellage détaché, la
sync ou le labo, et doit arrêter superviseur + workers + shells _run_ du projet,
même quand l'état de campagne ne liste aucun pid. Test de la sélection pure.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "tools" / "affichage_temps_reel.py"
_spec = importlib.util.spec_from_file_location("affichage_temps_reel", _MOD_PATH)
aff = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(aff)

R = r"C:\Users\flo\Desktop\Projet invest"
SELF = 4242


def _procs() -> list[tuple[int, str]]:
    return [
        (111, f'python.exe "{R}\\tools\\watch_economic_collectors.py" --profile copy-vault'),
        (112, f'python.exe "{R}\\tools\\collecter_bbo.py"'),
        (113, f'cmd.exe /K "{R}\\tools\\_run_poll_leaders.cmd"'),
        (SELF, f'python.exe "{R}\\tools\\affichage_temps_reel.py" --root .'),
        (114, f'python.exe "{R}\\tools\\affichage_temps_reel.py"'),
        (115, f'python.exe "{R}\\tools\\sceller_coffre_local.py" --root .'),
        (116, f'python.exe "{R}\\tools\\sync_complete_clone.py"'),
        (117, f'python.exe "{R}\\tools\\alina_quant_lab_console.py"'),
        (118, "python.exe C:\\autre_projet\\collecter_bbo.py"),
        (119, f'cmd.exe /c ""{R}\\POUSSER-GITHUB-FORCE.cmd""'),
    ]


def test_selecteur_tue_collecteurs_epargne_le_reste():
    res = aff._pids_collecteurs_a_tuer(_procs(), self_pid=SELF, racine=R)
    assert res == [111, 112, 113]


def test_selecteur_exclut_toujours_le_process_courant():
    # même si l'écran matche un marqueur collecteur, on ne se suicide jamais.
    procs = [(SELF, f'python.exe "{R}\\tools\\collecter_bbo.py"')]
    assert aff._pids_collecteurs_a_tuer(procs, self_pid=SELF, racine=R) == []


def test_selecteur_insensible_casse_et_slashes():
    procs = [(200, f"PYTHON.EXE {R.replace(chr(92), '/').upper()}/TOOLS/COLLECTER_BBO.PY")]
    assert aff._pids_collecteurs_a_tuer(procs, self_pid=SELF, racine=R) == [200]


def test_selecteur_ignore_hors_projet_et_pids_invalides():
    procs = [
        (0, f'python.exe "{R}\\tools\\collecter_bbo.py"'),       # pid invalide
        (-5, f'python.exe "{R}\\tools\\collecter_bbo.py"'),      # pid invalide
        (300, "python.exe D:\\ailleurs\\collecter_bbo.py"),       # hors racine
        (301, None),                                              # cmdline manquante
    ]
    assert aff._pids_collecteurs_a_tuer(procs, self_pid=SELF, racine=R) == []
