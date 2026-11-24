"""Normalisation CRLF -> LF des fichiers suivis (24/11/2026) : seule la version committée elle-même est écrite.

Verrouille, sur un vrai dépôt git :
- un fichier dont la seule différence est le CRLF est réécrit, et devient identique à l'octet au blob de l'index ;
- un fichier dont le CONTENU diffère (même en CRLF) n'est jamais touché ;
- ``--plan`` n'écrit rien ; un fichier déjà identique reste tel quel.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tools import normaliser_fins_de_ligne_datasets as N

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git absent")


def _git(depot: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=depot, check=True, capture_output=True, text=True).stdout


def _depot(tmp_path: Path) -> Path:
    depot = tmp_path / "depot"
    (depot / "datasets" / "safe").mkdir(parents=True)
    _git(depot, "init", "-q")
    _git(depot, "config", "user.email", "test@example.invalid")
    _git(depot, "config", "user.name", "test")
    _git(depot, "config", "core.autocrlf", "false")
    for nom in ("a", "b", "c", "d"):
        (depot / "datasets" / "safe" / f"{nom}.manifest.json").write_bytes(b'{\n  "k": 1,\n  "n": "%s"\n}\n' % nom.encode())
    _git(depot, "add", ".")
    _git(depot, "commit", "-q", "-m", "init")
    s = depot / "datasets" / "safe"
    (s / "a.manifest.json").write_bytes((s / "a.manifest.json").read_bytes().replace(b"\n", b"\r\n"))   # CRLF seul
    (s / "b.manifest.json").write_bytes(b'{\r\n  "k": 2,\r\n  "n": "b"\r\n}\r\n')                       # contenu change
    (s / "c.manifest.json").write_bytes(b'{\n  "k": 9,\n  "n": "c"\n}\n')                                # change, LF
    return depot


def test_seule_la_difference_de_fins_de_ligne_est_corrigee(tmp_path):
    depot = _depot(tmp_path)
    s = depot / "datasets" / "safe"
    avant_b, avant_c = (s / "b.manifest.json").read_bytes(), (s / "c.manifest.json").read_bytes()
    r = N.normaliser(depot, ouvriers=2, log=lambda *_: None)
    assert r["bilan"] == {"converti": 1, "autre_difference_laisse": 2, "deja_identique": 1}
    assert r["convertis"] == ["datasets/safe/a.manifest.json"]
    assert (s / "a.manifest.json").read_bytes() == _git(depot, "show", "HEAD:datasets/safe/a.manifest.json").encode()
    assert (s / "b.manifest.json").read_bytes() == avant_b and (s / "c.manifest.json").read_bytes() == avant_c
    statut = _git(depot, "status", "--porcelain")
    assert "a.manifest.json" not in statut and "b.manifest.json" in statut and "c.manifest.json" in statut


def test_le_plan_n_ecrit_rien(tmp_path):
    depot = _depot(tmp_path)
    a = depot / "datasets" / "safe" / "a.manifest.json"
    avant = a.read_bytes()
    r = N.normaliser(depot, ecrire=False, ouvriers=2, log=lambda *_: None)
    assert r["bilan"]["converti"] == 1 and a.read_bytes() == avant


def test_l_empreinte_est_celle_de_git():
    octets = b'{"x": 1}\n'
    attendu = subprocess.run(["git", "hash-object", "--stdin"], input=octets, capture_output=True, check=True).stdout
    assert N.empreinte_blob(octets) == attendu.decode().strip()
