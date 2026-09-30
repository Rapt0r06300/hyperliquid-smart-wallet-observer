"""[pépite 289] scale-out reconstruction : regrouper REDUCE successifs jusqu'au CLOSE."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.scale_out_reconstruction import reconstruire   # noqa: E402


def test_sortie_regroupee_jusqu_close():
    fills = [
        {"action": "REDUCE", "qty": 1.0, "prix": 110.0},
        {"action": "REDUCE", "qty": 1.0, "prix": 112.0},
        {"action": "CLOSE", "qty": 1.0, "prix": 114.0},
    ]
    r = reconstruire(fills)
    assert r["legs"] == 3 and r["qte_retiree"] == 3.0 and r["ferme"] is True and r["vwap_sortie"] == 112.0


def test_sortie_partielle_non_fermee():
    fills = [{"action": "REDUCE", "qty": 1.0, "prix": 110.0}]
    r = reconstruire(fills)
    assert r["ferme"] is False and r["qte_retiree"] == 1.0


def test_aucune_sortie():
    assert reconstruire([{"action": "OPEN", "qty": 1.0, "prix": 100.0}])["qte_retiree"] == "UNMEASURABLE"
