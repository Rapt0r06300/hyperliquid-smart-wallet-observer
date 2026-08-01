"""[COPY-VAULT lot2 #58] rebaseline après changement de collatéral : avant tout nouveau sizing."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.collateral_change_rebaseline import doit_rebaseline, nouvelle_reference   # noqa: E402


def test_rebaseline_apres_changement():
    r = doit_rebaseline(True)
    assert r["rebaseline"] is True and r["bloquer_sizing_avant"] is True


def test_pas_de_changement():
    assert doit_rebaseline(False)["rebaseline"] is False


def test_nouvelle_reference():
    assert nouvelle_reference(60000.0) == 60000.0
    assert nouvelle_reference(0.0) == "UNMEASURABLE"
