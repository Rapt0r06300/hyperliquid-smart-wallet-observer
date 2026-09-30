"""[COPY-VAULT lot2 #52] metadata-change rebootstrap : un changement de précision/min invalide les params."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.metadata_change_rebootstrap import doit_rebootstrap   # noqa: E402


def test_changement_declenche_rebootstrap():
    r = doit_rebootstrap({"tick_size": 0.01, "lot_size": 0.001, "min_notional": 10.0},
                         {"tick_size": 0.01, "lot_size": 0.01, "min_notional": 10.0})
    assert r["rebootstrap"] is True and "lot_size" in r["champs_changes"]


def test_inchange_pas_de_rebootstrap():
    meta = {"tick_size": 0.01, "lot_size": 0.001, "min_notional": 10.0}
    assert doit_rebootstrap(meta, dict(meta))["rebootstrap"] is False


def test_metadata_manquante():
    assert doit_rebootstrap(None, {"tick_size": 0.01})["rebootstrap"] is True
