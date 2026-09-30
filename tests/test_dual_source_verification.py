"""[COPY-VAULT lot2 #36] double source WS+REST : les fills live doivent correspondre à l'historique officiel."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.dual_source_verification import verifier   # noqa: E402


def test_coherent():
    assert verifier(["f1", "f2"], ["f1", "f2"])["coherent"] is True


def test_fill_manque_en_live():
    r = verifier(["f1"], ["f1", "f2"])
    assert r["coherent"] is False and r["manquants"] == ["f2"]


def test_fill_en_trop():
    r = verifier(["f1", "f2", "f3"], ["f1", "f2"])
    assert r["coherent"] is False and r["en_trop"] == ["f3"]
