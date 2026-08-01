"""[COPY-VAULT #65] authoritative close direction : la position courante décide BUY/SELL de la fermeture."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.authoritative_close_direction import direction_fermeture, direction_reduction, ACHAT, VENTE   # noqa: E402


def test_fermeture_selon_cote():
    assert direction_fermeture(2.0)["direction"] == VENTE     # fermer un long = vendre
    assert direction_fermeture(-2.0)["direction"] == ACHAT    # fermer un short = acheter


def test_rien_a_fermer():
    assert direction_fermeture(0.0)["direction"] is None
    assert direction_fermeture(None)["raison"] == "POSITION_INCONNUE"


def test_reduction_bornee():
    r = direction_reduction(2.0, 5.0)                         # réduire plus que détenu
    assert r["direction"] == VENTE and r["quantite"] == 2.0   # borné a la taille détenue
