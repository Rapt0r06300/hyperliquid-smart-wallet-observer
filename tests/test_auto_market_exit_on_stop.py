"""[ALL lot2 #18] auto market-exit au stop : sortie reduce-only de sens opposé, TIF adapté à la venue."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.auto_market_exit_on_stop import plan_exit_au_stop   # noqa: E402


def test_sortie_reduce_only_sens_oppose():
    r = plan_exit_au_stop({"BTC": {"taille": 0.5, "venue": "HL"}, "ETH": {"taille": -2.0, "venue": "BINANCE"}},
                          tif_par_venue={"HL": "IOC", "BINANCE": "FOK"})
    ordres = {o["coin"]: o for o in r["ordres_sortie"]}
    assert ordres["BTC"]["sens"] == "SELL" and ordres["BTC"]["tif"] == "IOC"
    assert ordres["ETH"]["sens"] == "BUY" and ordres["ETH"]["tif"] == "FOK"
    assert all(o["reduce_only"] for o in r["ordres_sortie"])


def test_position_nulle_ignoree():
    r = plan_exit_au_stop({"BTC": {"taille": 0.0, "venue": "HL"}})
    assert r["n"] == 0


def test_tif_defaut():
    r = plan_exit_au_stop({"BTC": {"taille": 1.0, "venue": "KRAKEN"}}, tif_defaut="IOC")
    assert r["ordres_sortie"][0]["tif"] == "IOC"
