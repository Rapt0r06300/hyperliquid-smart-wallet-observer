"""[pépite 269] invalid-size quarantine : niveau négatif/NaN/inf ou taille impossible invalide l'update."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.invalid_size_quarantine import valider_niveau   # noqa: E402


def test_niveau_valide():
    assert valider_niveau(100.0, 2.5)["etat"] == "VALIDE"


def test_taille_nulle_est_suppression():
    assert valider_niveau(100.0, 0.0)["etat"] == "SUPPRESSION"


def test_invalides():
    assert valider_niveau(100.0, -1.0)["etat"] == "INVALIDE"
    assert valider_niveau(100.0, float("inf"))["etat"] == "INVALIDE"
    assert valider_niveau(0.0, 2.0)["etat"] == "INVALIDE"
    assert valider_niveau(100.0, 1e9, taille_max=1000.0)["etat"] == "INVALIDE"
