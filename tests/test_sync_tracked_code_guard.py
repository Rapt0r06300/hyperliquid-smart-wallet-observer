"""AlinaSync : la garde fail-closed ne bloque que sur du CODE non commité.

Le churn des données suivies (catalog/, runtime/, data/… et fichiers de données
déposés sous un dossier de code) ne doit JAMAIS bloquer la synchronisation —
c'est ce qui empêchait AlinaSync de tourner après une récolte.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.sync_complete_clone import (
    _code_pathspecs,
    _modified_code_paths,
    _tracked_files_changed,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "alina@example.com")
    _git(root, "config", "user.name", "Alina Test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "tools").mkdir()
    (root / "tools" / "x.py").write_text("print('v1')\n", encoding="utf-8")
    (root / "src" / "hl_observer").mkdir(parents=True)
    (root / "src" / "hl_observer" / "mod.py").write_text("X = 1\n", encoding="utf-8")
    # Donnée déposée SOUS un dossier de code (extension de données).
    (root / "src" / "hl_observer" / "tape.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    # Arbres de données purs, suivis par git comme dans le vrai dépôt.
    (root / "catalog").mkdir()
    (root / "catalog" / "m.json").write_text('{"shard":1}\n', encoding="utf-8")
    (root / "runtime" / "data").mkdir(parents=True)
    (root / "runtime" / "data" / "fills.jsonl").write_text('{"f":1}\n', encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def test_churn_de_donnees_suivies_n_est_pas_bloquant(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    # Réécriture/rotation des données, exactement comme une récolte.
    (root / "catalog" / "m.json").write_text('{"shard":2}\n', encoding="utf-8")
    (root / "runtime" / "data" / "fills.jsonl").write_text('{"f":2}\n', encoding="utf-8")
    (root / "src" / "hl_observer" / "tape.jsonl").write_text('{"a":2}\n', encoding="utf-8")
    (root / "catalog" / "nouveau.json").write_text('{"shard":9}\n', encoding="utf-8")
    _git(root, "add", "catalog/nouveau.json")  # même stagé, c'est de la donnée
    assert _modified_code_paths(root) == []
    assert _tracked_files_changed(root) is False


def test_modification_de_code_reste_bloquante(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "tools" / "x.py").write_text("print('v2')\n", encoding="utf-8")
    modifies = _modified_code_paths(root)
    assert "tools/x.py" in modifies
    assert _tracked_files_changed(root) is True


def test_code_stage_est_detecte(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "src" / "hl_observer" / "mod.py").write_text("X = 2\n", encoding="utf-8")
    _git(root, "add", "src/hl_observer/mod.py")
    modifies = _modified_code_paths(root)
    assert "src/hl_observer/mod.py" in modifies
    assert _tracked_files_changed(root) is True


def test_pathspecs_excluent_les_racines_de_donnees(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    specs = set(_code_pathspecs(root))
    assert "tools/**" in specs
    assert "src/**" in specs
    assert "catalog/**" not in specs
    assert "runtime/**" not in specs
    assert ".git/**" not in specs
