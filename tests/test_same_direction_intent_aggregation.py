"""[pépite 246] same-direction intent aggregation : plusieurs achats du même coin partagent une intention."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.same_direction_intent_aggregation import agreger   # noqa: E402


def test_agregation_meme_sens():
    r = agreger([{"module": "a", "venue": "HL", "coin": "BTC", "montant_signe": 30.0},
                 {"module": "b", "venue": "HL", "coin": "BTC", "montant_signe": 50.0}])
    assert r["n_groupes"] == 1
    g = r["ordres_agreges"][0]
    assert g["montant_agrege"] == 80.0 and g["sens"] == "ACHAT" and g["n"] == 2


def test_sens_opposes_separes():
    r = agreger([{"module": "a", "venue": "HL", "coin": "BTC", "montant_signe": 30.0},
                 {"module": "b", "venue": "HL", "coin": "BTC", "montant_signe": -50.0}])
    assert r["n_groupes"] == 2                            # achat et vente separes


def test_contributions_conservees():
    r = agreger([{"module": "a", "venue": "HL", "coin": "BTC", "montant_signe": 30.0}])
    assert r["ordres_agreges"][0]["contributions"][0]["module"] == "a"
