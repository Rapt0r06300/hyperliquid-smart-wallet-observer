"""[PORTABILITE items 16,19] Les deux fichiers maitres et leur chaine ne dependent d'AUCUN chemin absolu
machine-specifique : ni C:\\Users\\flo, ni lettre de disque codee en dur, ni AppData/registre, ni Python
systeme impose. Tous les chemins viennent de %~dp0 (cote .cmd) ou de la racine passee en parametre (cote
Python). Verifie sur le TEXTE (portable donc testable sous Linux). 0 reseau.
"""
from __future__ import annotations

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
MAITRES = ["LANCER_HYPERSMART.cmd", "ANALYSER_BACKTESTS_REPLAYS.cmd", "tools/portable_env.cmd"]


def _lignes_commandes(txt: str):
    for ln in txt.splitlines():
        s = ln.strip()
        if s.upper().startswith("REM") or s.startswith("::") or s.startswith("echo"):
            continue
        yield ln


def test_aucun_chemin_utilisateur_en_dur():
    # On vise les COMMANDES reelles, pas les commentaires REM. Un commentaire qui DOCUMENTE
    # l'ancien bug de chemin absolu (« 'C:\\Users\\flo\\...' n'est pas reconnu ») est la preuve
    # du design portable, pas une dependance : c'est exactement pour cela que le lanceur
    # travaille en chemins RELATIFS depuis %~dp0.
    for rel in MAITRES:
        txt = (RACINE / rel).read_text(encoding="utf-8", errors="ignore")
        for ln in _lignes_commandes(txt):
            bas = ln.lower()
            assert "c:\\users\\flo" not in bas and "users\\flo" not in bas, "%s :: %r" % (rel, ln)
            assert "c:/users/flo" not in bas, "%s :: %r" % (rel, ln)
            assert "appdata" not in bas and "programdata" not in bas, "%s :: %r" % (rel, ln)
            assert "hkey_" not in bas and "reg add" not in bas and "reg query" not in bas, "%s :: %r" % (rel, ln)


def test_aucune_lettre_de_disque_codee_en_dur_dans_les_commandes():
    # une commande ne doit jamais referencer X:\... en dur (hors %~dp0 / %HYPERSMART_*%).
    motif = re.compile(r"[^%\w]([A-Za-z]:\\)")
    for rel in ("LANCER_HYPERSMART.cmd", "ANALYSER_BACKTESTS_REPLAYS.cmd"):
        txt = (RACINE / rel).read_text(encoding="utf-8", errors="ignore")
        for ln in _lignes_commandes(txt):
            # tolere les exemples entre guillemets d'aide ; on vise les vraies commandes de chemin.
            if "%~dp0" in ln or "%HYPERSMART" in ln:
                continue
            assert not motif.search(ln), "chemin absolu machine-specifique: %r (%s)" % (ln, rel)


def test_les_deux_maitres_ancrent_sur_dp0():
    for rel in ("LANCER_HYPERSMART.cmd", "ANALYSER_BACKTESTS_REPLAYS.cmd"):
        txt = (RACINE / rel).read_text(encoding="utf-8", errors="ignore")
        assert 'cd /d "%~dp0"' in txt, rel                    # se place dans SON dossier, quel qu'il soit
        assert "%~dp0" in txt, rel                            # chemins relatifs au fichier


def test_modules_de_donnees_calculent_depuis_la_racine():
    # les chemins de donnees runtime viennent d'un parametre `root`/`racine`, jamais du profil utilisateur.
    for rel in ("src/hl_observer/ops/session_catalog.py", "src/hl_observer/ops/session_harvest.py",
                "src/hl_observer/ops/registre_pids.py", "src/hl_observer/ops/lab_alpha.py"):
        src = (RACINE / rel).read_text(encoding="utf-8", errors="ignore")
        assert "Path.home()" not in src, rel
        assert ".expanduser()" not in src, rel
        assert "C:\\\\Users" not in src and "/Users/flo" not in src, rel
