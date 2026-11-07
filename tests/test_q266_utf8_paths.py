"""Q-266 — Tests d'encodage UTF-8 sur chemins avec espaces et accents.

Vérifie que les modules critiques gèrent correctement les chemins
contenant des espaces et caractères accentués (cas 'projet invest').
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


def test_project_root_has_space():
    root = Path(__file__).resolve().parents[1]
    assert " " in str(root), "Le projet doit être dans un chemin avec espace"


def test_config_runtime_flags_importable():
    from hl_observer.config import runtime_flags
    assert hasattr(runtime_flags, "load_security")


def test_json_write_read_utf8_path(tmp_path):
    accentued = tmp_path / "données été"
    accentued.mkdir()
    fp = accentued / "résultat.json"
    data = {"clé": "valeur accentuée", "montant": 350.0}
    fp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    loaded = json.loads(fp.read_text(encoding="utf-8"))
    assert loaded["clé"] == "valeur accentuée"


def test_pathlib_rglob_with_spaces(tmp_path):
    sub = tmp_path / "chemin avec espace" / "sous dossier"
    sub.mkdir(parents=True)
    (sub / "module.py").write_text("x = 1\n", encoding="utf-8")
    found = list(tmp_path.rglob("*.py"))
    assert len(found) == 1
    assert found[0].name == "module.py"
