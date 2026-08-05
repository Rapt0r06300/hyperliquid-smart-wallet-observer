from hl_observer.research.venue_readiness import (
    RegistreVenues, OFFLINE_READY, REQUIRES_NETWORK, NON_IMPLEMENTE)


def test_registre_venues_honnete():
    r = RegistreVenues()
    r.declarer("hyperliquid", OFFLINE_READY, requis=True)
    r.declarer("dydx", OFFLINE_READY)
    r.declarer("binance", OFFLINE_READY)
    r.declarer("bybit", REQUIRES_NETWORK)
    r.declarer("okx", REQUIRES_NETWORK)
    assert r.ready_multi_venue()["ready"] is True                      # aucune requise NON_IMPLEMENTE
    assert r.par_capacite(REQUIRES_NETWORK) == ["bybit", "okx"]        # honnete : live non prouve ici


def test_venue_requise_non_implementee_bloque():
    r = RegistreVenues()
    r.declarer("hyperliquid", OFFLINE_READY, requis=True)
    r.declarer("gmx", NON_IMPLEMENTE, requis=True)
    rm = r.ready_multi_venue()
    assert rm["ready"] is False and "gmx" in rm["requises_non_pretes"]
