"""Le préchargement des blobs d'un clone partiel se fait en UNE requête fetch, pas un aller-retour par blob."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import alina_git_code_sync as S  # noqa: E402


class _Faux:
    def __init__(self, promisor: bytes) -> None:
        self.appels: list[tuple] = []
        self.promisor = promisor

    def command(self, *args, input_bytes=None, check=True, timeout=300, expected_returncodes=()):
        self.appels.append((args, input_bytes))
        if args[:2] == ("config", "--get"):
            return subprocess.CompletedProcess(args, 0, self.promisor, b"")
        if args[0] == "ls-tree":
            chemins = args[args.index("--") + 1:]
            sortie = b"".join(b"100644 blob %040x\t%s\0" % (i + 1, c.encode()) for i, c in enumerate(chemins))
            return subprocess.CompletedProcess(args, 0, sortie, b"")
        return subprocess.CompletedProcess(args, 0, b"", b"")


def test_un_seul_fetch_pour_tous_les_blobs() -> None:
    f = _Faux(b"true\n")
    S.Synchronizer._prefetch_blobs_par_lot(f, "abc", [f"catalog/x{i}.json" for i in range(450)])
    fetchs = [a for a in f.appels if "fetch" in a[0]]
    assert len(fetchs) == 1 and "--stdin" in fetchs[0][0]
    assert len([a for a in f.appels if a[0][0] == "ls-tree"]) == 3           # lots de 200 chemins


def test_clone_complet_ne_fetch_rien() -> None:
    f = _Faux(b"")
    S.Synchronizer._prefetch_blobs_par_lot(f, "abc", ["a.py"])
    assert not [a for a in f.appels if "fetch" in a[0]]
