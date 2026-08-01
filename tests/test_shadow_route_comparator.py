"""[pépite 243] shadow-route comparator : simuler les routes non choisies sans changer le trade réel."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.routing.shadow_route_comparator import comparer   # noqa: E402


def test_route_choisie_optimale():
    r = comparer(route_choisie="HL", resultats_bps={"HL": 12.0, "BIN": 8.0})
    assert r["choix_optimal"] is True and r["gain_manque_bps"] == 0.0 and r["shadow_only"] is True


def test_shadow_aurait_fait_mieux():
    r = comparer(route_choisie="HL", resultats_bps={"HL": 8.0, "BIN": 12.0})
    assert r["choix_optimal"] is False and r["meilleure_route"] == "BIN" and r["gain_manque_bps"] == 4.0


def test_choisie_sans_resultat():
    assert comparer(route_choisie="ZZ", resultats_bps={"HL": 8.0})["comparable"] is False
