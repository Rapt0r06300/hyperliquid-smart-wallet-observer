"""[pépite 233] hedge-fallback prevalidation : le secours validé avant d'ouvrir la première jambe."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.routing.hedge_fallback_prevalidation import peut_ouvrir_premiere_jambe   # noqa: E402


def test_secours_valide():
    r = peut_ouvrir_premiere_jambe(secours_venue_trading=True, secours_liquidite_ok=True, secours_etat_frais=True)
    assert r["peut_ouvrir"] is True


def test_secours_liquidite_manquante():
    r = peut_ouvrir_premiere_jambe(secours_venue_trading=True, secours_liquidite_ok=False, secours_etat_frais=True)
    assert r["peut_ouvrir"] is False and "liquidite" in r["secours_manques"]


def test_tout_manque():
    r = peut_ouvrir_premiere_jambe(secours_venue_trading=False, secours_liquidite_ok=False, secours_etat_frais=False)
    assert len(r["secours_manques"]) == 3
