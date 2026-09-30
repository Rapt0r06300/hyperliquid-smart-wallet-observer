"""[ALL lot2 #26] QoS des requêtes : emergency close > hedge > cancel > reconcile > data refresh > research."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.api_governance.request_qos import FileQoS, rang   # noqa: E402


def test_ordre_de_priorite():
    assert rang("EMERGENCY_CLOSE") < rang("HEDGE") < rang("CANCEL") < rang("RECONCILE") < rang("DATA_REFRESH") < rang("RESEARCH")


def test_file_sert_le_plus_prioritaire():
    f = FileQoS()
    f.ajouter("r1", categorie="RESEARCH")
    f.ajouter("r2", categorie="EMERGENCY_CLOSE")
    f.ajouter("r3", categorie="CANCEL")
    assert f.suivant() == "r2" and f.suivant() == "r3" and f.suivant() == "r1"


def test_categorie_inconnue_derniere():
    f = FileQoS()
    f.ajouter("x", categorie="???")
    f.ajouter("h", categorie="HEDGE")
    assert f.ordonner()[0] == "h"
