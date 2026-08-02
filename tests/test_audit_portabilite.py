"""[PORTABILITE item 12] L'audit repo-complet DÉTECTE les briseurs de portabilité et PROUVE que le
runtime actif (src/hl_observer + tools + .cmd maîtres) n'en contient aucun. Verrou permanent : toute
régression (chemin absolu, C:\\Users, /home/, registre) réintroduite fera échouer ce test. 0 réseau.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import audit_portabilite as A                              # noqa: E402


def _cats(violations):
    return {v["categorie"] for v in violations}


def test_detecte_chemin_absolu_disque(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "x.py").write_text('CHEMIN = "C:\\\\Users\\\\flo\\\\data"\n', encoding="utf-8")
    cats = _cats(A.auditer(tmp_path))
    assert "chemin_absolu_disque" in cats or "users_flo" in cats


def test_detecte_chemin_sandbox(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "y.py").write_text('OUT = "/home/claude/hypersmart/runtime"\n', encoding="utf-8")
    assert "chemin_sandbox_profil" in _cats(A.auditer(tmp_path))


def test_detecte_registre(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "z.py").write_text("import winreg\n", encoding="utf-8")
    assert "registre_windows" in _cats(A.auditer(tmp_path))


def test_ignore_les_commentaires(tmp_path):
    # un commentaire qui DOCUMENTE l'ancien bug ne casse pas la portabilité -> pas une violation.
    (tmp_path / "LANCER_HYPERSMART.cmd").write_text(
        "cd /d \"%~dp0\"\nREM 'C:\\Users\\flo\\Desktop\\Projet' n'est pas reconnu\n", encoding="utf-8")
    assert A.auditer(tmp_path) == []


def test_tolere_dp0(tmp_path):
    # %~dp0 est un chemin DÉRIVÉ portable, jamais une violation.
    (tmp_path / "LANCER_HYPERSMART.cmd").write_text('call "%~dp0tools\\portable_env.cmd"\n', encoding="utf-8")
    assert A.auditer(tmp_path) == []


def test_le_runtime_actif_du_depot_est_portable():
    # LE verrou : le vrai runtime (src/hl_observer + tools + .cmd maîtres) ne contient AUCUN briseur.
    violations = A.auditer(RACINE)
    assert violations == [], A.formater(violations)
