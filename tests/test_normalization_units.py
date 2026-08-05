import pytest

from hl_observer.research.normalization_units import (
    normaliser_open_interest, normaliser_sens_liquidation, MethodologieMarkIndex, symbol_master_pit)


def test_normaliser_open_interest():
    assert normaliser_open_interest(1000.0, unite="usd")["oi_usd"] == 1000.0
    assert normaliser_open_interest(2.0, unite="base", prix=50000.0)["oi_usd"] == 100000.0
    with pytest.raises(ValueError):
        normaliser_open_interest(1.0, unite="bananes")


def test_normaliser_sens_liquidation():
    assert normaliser_sens_liquidation("long", convention="position")["ordre_force"] == "SELL"
    assert normaliser_sens_liquidation("short", convention="position")["ordre_force"] == "BUY"
    assert normaliser_sens_liquidation("buy", convention="order")["ordre_force"] == "BUY"


def test_methodologie_mark_index_versionnee():
    m = MethodologieMarkIndex()
    m.enregistrer("v1", description="mediane 3 venues", formule="median(a,b,c)")
    m.enregistrer("v2", description="ponderee volume", formule="vwap")
    assert m.versions() == ["v1", "v2"] and m.obtenir("v1")["formule"] == "median(a,b,c)"


def test_symbol_master_pit_pas_de_futur():
    hist = [{"venue": "x", "symbole": "BTC", "canonique": "BTC-OLD", "depuis": 0},
            {"venue": "x", "symbole": "BTC", "canonique": "BTC-NEW", "depuis": 100}]
    assert symbol_master_pit(hist, "x", "BTC", 50)["canonique"] == "BTC-OLD"     # pas le futur BTC-NEW
    assert symbol_master_pit(hist, "x", "BTC", 150)["canonique"] == "BTC-NEW"
