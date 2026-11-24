"""L'adoption des commits distants garde les dates de l'index git (24/11/2026).

Mesure : après chaque push, ``read-tree <new>`` reconstruisait les 1 941 337 entrées de l'index SANS date ni taille ;
chaque ``git status`` suivant (Codex compris) re-hachait alors tous les fichiers suivis (> 10 min, jusqu'à 19 git
empilés, 11 Go). Verrouille :
- sur un vrai dépôt git, ``read-tree -m -i <old> <new>`` garde la date des entrées inchangées (le simple
  ``read-tree <new>`` la met à zéro) et produit exactement l'arbre ``<new>`` ;
- l'outil de synchronisation utilise cette fusion, et retombe sur l'ancien ``read-tree <new>`` si git la refuse.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tools.alina_git_code_sync import Synchronizer

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git absent")


def _git(depot: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=depot, check=True, capture_output=True, text=True).stdout


def _mtimes(depot: Path) -> dict[str, int]:
    """``chemin -> mtime (secondes)`` lus dans l'index (``ls-files --debug``)."""
    sortie, chemin, dates = _git(depot, "ls-files", "--debug"), None, {}
    for ligne in sortie.splitlines():
        if not ligne.startswith(" "):
            chemin = ligne.strip()
        elif ligne.strip().startswith("mtime:") and chemin:
            dates[chemin] = int(ligne.split(":")[1])
    return dates


def _depot(tmp_path: Path) -> tuple[Path, str, str]:
    depot = tmp_path / "depot"
    depot.mkdir()
    _git(depot, "init", "-q")
    _git(depot, "config", "user.email", "test@example.invalid")
    _git(depot, "config", "user.name", "test")
    for nom in ("a.txt", "b.txt", "c.txt"):
        (depot / nom).write_text(f"{nom} v1\n", encoding="utf-8")
    _git(depot, "add", ".")
    _git(depot, "commit", "-q", "-m", "A")
    a = _git(depot, "rev-parse", "HEAD").strip()
    (depot / "b.txt").write_text("b.txt v2\n", encoding="utf-8")
    _git(depot, "commit", "-q", "-am", "B")
    b = _git(depot, "rev-parse", "HEAD").strip()
    _git(depot, "read-tree", a)
    _git(depot, "update-index", "-q", "--refresh")       # l'index de A, avec ses dates
    return depot, a, b


def test_le_read_tree_simple_efface_les_dates(tmp_path):
    depot, _a, b = _depot(tmp_path)
    assert _mtimes(depot)["a.txt"] > 0
    _git(depot, "read-tree", b)
    assert _mtimes(depot)["a.txt"] == 0                    # le défaut mesuré sur le vrai dépôt


def test_la_fusion_a_deux_arbres_garde_les_dates_et_donne_l_arbre_distant(tmp_path):
    depot, a, b = _depot(tmp_path)
    avant = _mtimes(depot)
    _git(depot, "read-tree", "-m", "-i", a, b)
    apres = _mtimes(depot)
    assert apres["a.txt"] == avant["a.txt"] > 0 and apres["c.txt"] == avant["c.txt"] > 0   # inchangés : gardés
    assert _git(depot, "write-tree").strip() == _git(depot, "rev-parse", f"{b}^{{tree}}").strip()


def _adopter(tmp_path: Path, refus_de_la_fusion: bool):
    task = Synchronizer(tmp_path)
    old, new = "1" * 40, "2" * 40
    commandes: list[tuple[str, ...]] = []

    def fausse_commande(*args: str, **kwargs):
        commandes.append(args)
        if args[0] == "replay":
            return subprocess.CompletedProcess(args, 0, f"update refs/heads/main {new} {old}\n".encode(), b"")
        if args[:3] == ("read-tree", "-m", "-i") and refus_de_la_fusion:
            return subprocess.CompletedProcess(args, 128, b"", b"fatal: Entry not uptodate")
        if args[:2] == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess(args, 0, f"{new}\n".encode(), b"")
        return subprocess.CompletedProcess(args, 0, b"", b"")

    task.command = fausse_commande  # type: ignore[method-assign]
    task._assert_no_new_code_changes = lambda: None  # type: ignore[method-assign]
    assert task._try_git_replay("remote", old, "base") is True
    return task, commandes, old, new


def test_l_outil_utilise_la_fusion_qui_garde_les_dates(tmp_path):
    task, commandes, old, new = _adopter(tmp_path, refus_de_la_fusion=False)
    assert ("read-tree", "-m", "-i", old, new) in commandes
    assert ("read-tree", new) not in commandes
    assert task.report["adoption_index"] == "READ_TREE_DEUX_ARBRES_DATES_GARDEES"


def test_si_git_refuse_la_fusion_l_outil_retombe_sur_l_ancien_read_tree(tmp_path):
    task, commandes, old, new = _adopter(tmp_path, refus_de_la_fusion=True)
    i_fusion = commandes.index(("read-tree", "-m", "-i", old, new))
    i_repli = commandes.index(("read-tree", new))
    assert i_fusion < i_repli < commandes.index(("update-ref", "refs/heads/main", new, old))
    assert task.report["adoption_index"] == "READ_TREE_SIMPLE_REPLI"
