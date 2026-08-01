"""[pépite 245] global intent netting : netter cross-module avant le PaperEngine."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.global_intent_netting import netter   # noqa: E402


def test_netting_cross_module():
    r = netter([{"module": "copy", "venue": "HL", "coin": "BTC", "montant_signe": 80.0},
                {"module": "arb", "venue": "HL", "coin": "BTC", "montant_signe": -50.0}])
    cle = r["net_par_cle"]["HL/BTC"]
    assert cle["net"] == 30.0 and cle["brut"] == 130.0 and cle["economie"] == 100.0


def test_cles_separees():
    r = netter([{"module": "a", "venue": "HL", "coin": "BTC", "montant_signe": 10.0},
                {"module": "b", "venue": "HL", "coin": "ETH", "montant_signe": 5.0}])
    assert r["n_cles"] == 2


def test_intent_invalide_ignore():
    r = netter([{"module": "a", "venue": "HL", "coin": "BTC", "montant_signe": None},
                {"module": "b", "venue": "HL", "coin": "BTC", "montant_signe": 10.0}])
    assert r["net_par_cle"]["HL/BTC"]["net"] == 10.0
