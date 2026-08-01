"""[ALL #99] execution-model calibration : biais systématique prédit vs réalisé -> modèle non fiable."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.execution_model_calibration import CalibrationModele   # noqa: E402


def test_biais_systematique_non_fiable():
    c = CalibrationModele()
    for _ in range(25):
        c.enregistrer(99.0, 100.0, sens="ACHAT")         # prédit 99 alors que réalisé 100 -> optimiste ~+100 bps
    r = c.fiable(seuil_biais_bps=5.0, min_echantillons=20)
    assert r["fiable"] is False and r["raison"] == "BIAIS_SYSTEMATIQUE_NON_FIABLE"


def test_modele_calibre_fiable():
    c = CalibrationModele()
    for _ in range(25):
        c.enregistrer(100.0, 100.0, sens="ACHAT")        # sans biais
    assert c.fiable(min_echantillons=20)["fiable"] is True


def test_echantillon_insuffisant_unknown():
    c = CalibrationModele()
    c.enregistrer(99.0, 100.0)
    assert c.fiable(min_echantillons=20)["fiable"] is None   # jamais fiable par défaut
