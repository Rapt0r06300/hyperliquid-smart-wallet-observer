from hl_observer.research.venue_capabilities import (
    RegistreCapacitesVenues, registre_par_defaut, OFFLINE_READY, REQUIRES_NETWORK, NON_IMPLEMENTE)


def test_registre_par_defaut_honnete():
    r = registre_par_defaut()
    assert r.capacite("hyperliquid") == OFFLINE_READY
    assert r.capacite("dydx") == OFFLINE_READY and r.capacite("binance") == OFFLINE_READY
    assert r.capacite("bybit") == REQUIRES_NETWORK and r.capacite("nansen") == REQUIRES_NETWORK
    rd = r.ready()
    assert rd["ready"] is True                                   # aucune requise NON_IMPLEMENTE
    assert "bybit" in rd["requiert_reseau"] and "hyperliquid" in rd["offline_ready"]
    assert r.flux_supportes("hyperliquid") == ["book", "funding", "liquidations", "oi", "trades"]


def test_venue_requise_non_implementee_bloque():
    r = RegistreCapacitesVenues()
    r.declarer("hyperliquid", OFFLINE_READY, requis=True)
    r.declarer("okx", NON_IMPLEMENTE, requis=True)
    rd = r.ready()
    assert rd["ready"] is False and "okx" in rd["requises_non_pretes"]
