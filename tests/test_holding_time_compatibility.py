"""[pépite 286] holding-time compatibility : tenir 3 secondes ≠ tenir plusieurs heures pour la copie."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.holding_time_compatibility import evaluer   # noqa: E402


def test_holding_long_compatible():
    r = evaluer(duree_holding_s=3600.0, latence_copie_s=1.0)   # ratio ~0.0003
    assert r["etat"] == "COMPATIBLE"


def test_holding_court_incompatible():
    r = evaluer(duree_holding_s=0.5, latence_copie_s=1.0)      # latence > holding
    assert r["etat"] == "INCOMPATIBLE"


def test_duree_invalide():
    assert evaluer(0.0, latence_copie_s=1.0)["etat"] == "UNMEASURABLE"
