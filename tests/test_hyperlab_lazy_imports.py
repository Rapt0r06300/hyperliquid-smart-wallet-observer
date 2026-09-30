"""Regression : les briques HyperLab legeres n'importent pas le data plane."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_calibration_session_et_leakage_sans_pyarrow() -> None:
    project_root = Path(__file__).resolve().parents[1]
    source_root = project_root / "src"
    code = """
import importlib.abc
import sys

class BlockPyArrow(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "pyarrow" or fullname.startswith("pyarrow."):
            raise ModuleNotFoundError("pyarrow bloque pour ce test")
        return None

sys.meta_path.insert(0, BlockPyArrow())
from hl_observer.hyperlab import calibration, leakage, session
assert calibration.parametres_calibres([], [], [])["spread_bps"] is None
assert leakage.verifier_pas_de_fuite([0], [1], [2])["fuite"] is False
assert session.Session("lazy-import", ts=0.0).statut == "INCOMPLETE"
assert "hl_observer.hyperlab.data_plane" not in sys.modules
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
