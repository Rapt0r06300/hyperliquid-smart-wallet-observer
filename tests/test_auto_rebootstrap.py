"""[COPY-VAULT lot2 #40] auto-rebootstrap : sync_confidence sous seuil -> rebootstrap complet."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.auto_rebootstrap import doit_rebootstrap   # noqa: E402


def test_sous_seuil_rebootstrap():
    r = doit_rebootstrap(0.4, seuil=0.6)
    assert r["rebootstrap"] is True and r["raison"] == "SOUS_SEUIL_SYNC"


def test_au_dessus_seuil():
    assert doit_rebootstrap(0.8, seuil=0.6)["rebootstrap"] is False


def test_score_inconnu_rebootstrap():
    assert doit_rebootstrap(None)["rebootstrap"] is True
