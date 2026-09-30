"""[pépite 288] scale-in reconstruction : regrouper OPEN+ADD successifs en une séquence de construction."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.scale_in_reconstruction import reconstruire   # noqa: E402


def test_construction_regroupee():
    fills = [
        {"action": "OPEN", "qty": 1.0, "prix": 100.0, "sens": "LONG"},
        {"action": "ADD", "qty": 1.0, "prix": 102.0, "sens": "LONG"},
        {"action": "REDUCE", "qty": 0.5, "prix": 105.0, "sens": "LONG"},
    ]
    r = reconstruire(fills)
    assert r["legs"] == 2 and r["qte_cumulee"] == 2.0 and r["vwap_entree"] == 101.0


def test_sens_conserve():
    fills = [{"action": "OPEN", "qty": 2.0, "prix": 50.0, "sens": "SHORT"}]
    assert reconstruire(fills)["sens"] == "SHORT"


def test_aucune_construction():
    assert reconstruire([{"action": "REDUCE", "qty": 1.0, "prix": 100.0}])["qte_cumulee"] == "UNMEASURABLE"
