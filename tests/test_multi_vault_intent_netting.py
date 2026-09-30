"""[COPY-VAULT #80] multi-vault intent netting : +$80 et -$50 sur le même coin -> net +$30."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.multi_vault_intent_netting import netter   # noqa: E402


def test_netting_meme_coin():
    r = netter([{"coin": "BTC", "montant_signe": 80.0}, {"coin": "BTC", "montant_signe": -50.0}])
    assert r["net_par_coin"]["BTC"] == 30.0
    assert r["brut_par_coin"]["BTC"] == 130.0
    assert r["economie_par_coin"]["BTC"] == 100.0        # partie qui s'annule (spread/frais évités)


def test_coins_separes():
    r = netter([{"coin": "BTC", "montant_signe": 80.0}, {"coin": "ETH", "montant_signe": -50.0}])
    assert r["net_par_coin"] == {"BTC": 80.0, "ETH": -50.0}


def test_intent_invalide_ignore():
    r = netter([{"coin": "BTC", "montant_signe": None}, {"coin": "BTC", "montant_signe": 10.0}])
    assert r["net_par_coin"]["BTC"] == 10.0
