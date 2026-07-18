"""K3 — calibration : un score 70% doit gagner ~70% du temps."""
from __future__ import annotations

import pytest

from hl_observer.modeling.probability_calibration import erreur_calibration, est_calibre


def test_parfaitement_calibre():
    # 100 preds a 0.7 dont 70 gagnent -> bin parfaitement calibre
    probas = [0.7] * 100
    resultats = [1] * 70 + [0] * 30
    assert erreur_calibration(probas, resultats) == pytest.approx(0.0, abs=1e-6)
    assert est_calibre(probas, resultats) is True


def test_mal_calibre():
    # dit 90% mais ne gagne que 40% -> ECE ~0.5
    probas = [0.9] * 100
    resultats = [1] * 40 + [0] * 60
    assert erreur_calibration(probas, resultats) > 0.1
    assert est_calibre(probas, resultats) is False


def test_pas_de_donnees_non_mesurable():
    assert erreur_calibration([], []) is None
    assert est_calibre([], []) is False
