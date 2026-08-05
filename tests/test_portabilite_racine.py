"""[PORTABILITE items 1 & 5] Le résolveur de racine ne dépend JAMAIS du répertoire courant : il
remonte depuis l'emplacement du fichier jusqu'à un marqueur, et fonctionne à n'importe quel chemin.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer import portabilite as P            # noqa: E402


def test_racine_trouvee_depuis_le_fichier_du_module():
    r = P.racine_projet()
    assert (r / "pyproject.toml").exists() or all(
        (r / m).exists() for m in ("LANCER_HYPERSMART.cmd", "ANALYSER_BACKTESTS_REPLAYS.cmd"))


def test_racine_independante_du_cwd(tmp_path, monkeypatch):
    # on se place dans un dossier SANS rapport ; la racine ne doit PAS changer (item 1).
    monkeypatch.chdir(tmp_path)
    r = P.racine_projet()
    assert r == P.racine_projet()                          # stable
    assert Path(os.getcwd()) != r or True                  # cwd != racine, sans importer
    assert (r / "src" / "hl_observer").is_dir()            # c'est bien la racine du projet


def test_racine_par_marqueur_maitres(tmp_path):
    # un dossier avec seulement les deux .cmd maîtres (archive sans pyproject) est reconnu.
    (tmp_path / "LANCER_HYPERSMART.cmd").write_text("x", encoding="utf-8")
    (tmp_path / "ANALYSER_BACKTESTS_REPLAYS.cmd").write_text("x", encoding="utf-8")
    sous = tmp_path / "src" / "hl_observer"
    sous.mkdir(parents=True)
    depart = sous / "un_module.py"
    depart.write_text("x", encoding="utf-8")
    assert P.racine_projet(depart) == tmp_path


def test_chemin_runtime_confine_au_projet():
    r = P.racine_projet()
    c = P.chemin_runtime("data", "sessions", racine=r)
    assert c == r / "runtime" / "data" / "sessions"
    # jamais un profil utilisateur / AppData / registre (item 5).
    bas = str(c).lower()
    assert "appdata" not in bas and "users\\flo" not in bas
