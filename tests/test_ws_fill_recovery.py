"""[ARB lot2 #15] recovery par fill WS : un fill reçu avant l'ACK rattache/résout un ordre UNKNOWN."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.ws_fill_recovery import rattacher_fill   # noqa: E402


def test_rattache_par_client_order_id():
    unknown = {"c1": {"coin": "BTC", "cote": "BUY"}}
    r = rattacher_fill({"client_order_id": "c1", "coin": "BTC", "cote": "BUY"}, unknown)
    assert r["resolu"] is True and r["order_id"] == "c1" and r["statut"] == "FILLED"


def test_rattache_par_coin_cote():
    unknown = {"c1": {"coin": "ETH", "cote": "SELL"}}
    r = rattacher_fill({"coin": "ETH", "cote": "SELL"}, unknown)
    assert r["resolu"] is True and r["methode"] == "COIN_COTE"


def test_fill_orphelin():
    r = rattacher_fill({"coin": "XRP", "cote": "BUY"}, {"c1": {"coin": "BTC", "cote": "BUY"}})
    assert r["resolu"] is False and r["statut"] == "FILL_ORPHELIN"
