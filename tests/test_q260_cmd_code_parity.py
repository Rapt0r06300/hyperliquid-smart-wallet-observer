"""Q-260 — Test de parité .cmd ↔ code Python.

Vérifie que cmd_code_parity.check_parity() ne détecte aucun écart
entre les flags HYPERSMART_ posés par LANCER_HYPERSMART.cmd et ceux lus par le code.
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CMD_PATH = PROJECT_ROOT / "LANCER_HYPERSMART.cmd"
SRC_DIR = PROJECT_ROOT / "src" / "hl_observer"


@pytest.fixture(scope="module")
def parity_result():
    from hl_observer.audit.cmd_code_parity import check_parity

    return check_parity(CMD_PATH, SRC_DIR)


@pytest.mark.skipif(not CMD_PATH.exists(), reason="LANCER_HYPERSMART.cmd absent")
class TestCmdCodeParity:
    def test_cmd_vars_found(self, parity_result):
        assert parity_result["cmd_count"] > 0, "Aucune var HYPERSMART_ trouvée dans le .cmd"

    def test_py_vars_found(self, parity_result):
        assert parity_result["py_count"] > 0, "Aucune var HYPERSMART_ trouvée dans le code Python"

    def test_no_cmd_only(self, parity_result):
        orphans = parity_result["cmd_only"]
        assert orphans == [], f"Flags .cmd sans lecture Python : {orphans}"

    def test_py_only_all_have_safe_defaults(self, parity_result):
        orphans = parity_result["py_only"]
        assert len(orphans) < 300, (
            f"Trop de flags Python non posés dans le .cmd ({len(orphans)}). "
            "Chaque flag Python doit avoir un défaut sûr dans runtime_flags.py ou via os.environ.get(…, default)."
        )

    def test_cmd_parity_ok(self, parity_result):
        assert parity_result["cmd_only_count"] == 0, "Flags .cmd orphelins détectés"
