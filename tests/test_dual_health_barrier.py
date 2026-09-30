"""[ARB #38] dual-health barrier : pas d'ouverture si une source est dégradée, même prix fantastique."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.dual_health_barrier import peut_ouvrir   # noqa: E402


def test_les_deux_saines():
    assert peut_ouvrir("SAINE", "OK")["peut_ouvrir"] is True
    assert peut_ouvrir(True, True)["peut_ouvrir"] is True


def test_une_degradee_bloque():
    r = peut_ouvrir("SAINE", "DEGRADEE")
    assert r["peut_ouvrir"] is False and "B" in r["sources_degradees"]


def test_sante_inconnue_fail_closed():
    assert peut_ouvrir("SAINE", None)["peut_ouvrir"] is False        # inconnu = dégradé
    assert peut_ouvrir("???", "OK")["peut_ouvrir"] is False
