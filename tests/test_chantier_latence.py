"""L'outil chantier-latence trouve le dernier espace de travail du labo et refuse proprement s'il n'y en a pas."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("chantier_latence", RACINE / "tools" / "chantier_latence.py")
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(RACINE))
    sys.path.insert(0, str(RACINE / "src"))
    spec.loader.exec_module(m)
    return m


L = _mod()


def test_prend_le_workspace_le_plus_recent(tmp_path):
    base = tmp_path / "runtime" / "reports" / "copy_vault_quant_lab"
    for nom in ("20261111T000000000000Z", "20261112T120000000000Z"):
        ws = base / nom / "workspace" / "runtime" / "data"
        ws.mkdir(parents=True)
        (base / nom / "workspace" / "SAFE_INPUT_MANIFEST.json").write_text("{}", encoding="utf-8")
    choisi = L._dernier_workspace(tmp_path)
    assert choisi is not None and choisi.parent.name == "20261112T120000000000Z"


def test_ignore_un_run_sans_workspace(tmp_path):
    base = tmp_path / "runtime" / "reports" / "copy_vault_quant_lab"
    (base / "20261112T120000000000Z").mkdir(parents=True)        # run sans workspace
    ok = base / "20261111T000000000000Z" / "workspace" / "runtime" / "data"
    ok.mkdir(parents=True)
    assert L._dernier_workspace(tmp_path).parent.name == "20261111T000000000000Z"


def test_main_sans_workspace(tmp_path, capsys):
    assert L.main(["--root", str(tmp_path)]) == 2
    assert "aucun espace de travail" in capsys.readouterr().out
