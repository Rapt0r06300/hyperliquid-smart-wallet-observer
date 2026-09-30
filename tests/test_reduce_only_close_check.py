"""[lot2 #90] reduce-only close vérifié contre la position, pas le cash."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.risk_gates.reduce_only_close_check import peut_fermer   # noqa: E402


def test_fermeture_inferieure_a_la_position():
    r = peut_fermer(0.5, 2.0)
    assert r["peut_fermer"] is True and r["verifie_contre"] == "POSITION_PAS_CASH"


def test_fermeture_superieure_refusee():
    r = peut_fermer(3.0, 2.0)
    assert r["peut_fermer"] is False and r["raison"] == "FERMETURE_SUPERIEURE_A_LA_POSITION"


def test_short_ferme_par_valeur_absolue():
    assert peut_fermer(1.0, -2.0)["peut_fermer"] is True
    assert peut_fermer(None, -2.0)["peut_fermer"] is False
