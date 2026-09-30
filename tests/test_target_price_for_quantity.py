"""[lot2 #87] double calcul target price : book walk indépendant, carnet insuffisant -> UNMEASURABLE."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.quoting.target_price_for_quantity import prix_pour_quantite   # noqa: E402


def test_vwap_book_walk():
    niveaux = [(100.0, 1.0), (101.0, 3.0)]
    r = prix_pour_quantite(niveaux, 2.0)                 # 1@100 + 1@101
    assert r["vwap"] == 100.5 and r["pire_prix"] == 101.0


def test_carnet_insuffisant():
    r = prix_pour_quantite([(100.0, 1.0)], 5.0)
    assert r["vwap"] == "UNMEASURABLE" and r["raison"] == "CARNET_INSUFFISANT"


def test_quantite_invalide():
    assert prix_pour_quantite([(100.0, 1.0)], 0.0)["vwap"] == "UNMEASURABLE"


def test_niveau_invalide_refuse_sans_extrapolation():
    r = prix_pour_quantite([(100.0, 0.25), ("prix-invalide", 1.0)], 1.0)
    assert r == {"vwap": "UNMEASURABLE", "raison": "NIVEAU_INVALIDE"}
