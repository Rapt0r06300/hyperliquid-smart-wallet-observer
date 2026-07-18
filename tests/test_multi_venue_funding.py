"""Funding multi-venues — chaque paire de venues à dispersion suffisante = un carry candidat.
Plus de venues = plus d'ouvertures. Sens correct (long funding bas / short haut)."""
from __future__ import annotations

from hl_observer.market.multi_venue_funding import classer_carries_multi_venue, compter_opportunites


def test_paires_classees_et_sens_correct():
    r = classer_carries_multi_venue("BTC", {"HL": 0.05, "Binance": 0.35, "Bybit": 0.20},
                                    cout_entree_bps=11.0)
    assert len(r) == 3                                   # 3 venues -> 3 paires
    best = r[0]                                          # meilleur écart = HL(0.05) vs Binance(0.35)
    assert best["long_venue"] == "HL" and best["short_venue"] == "Binance"
    assert r == sorted(r, key=lambda x: -x["gain_net_bps"])   # trié par gain net


def test_dispersion_faible_ecartee():
    r = classer_carries_multi_venue("BTC", {"HL": 0.125, "Bybit": 0.126}, cout_entree_bps=11.0)
    assert r == []                                      # écart trop faible -> aucune ouverture


def test_plus_de_venues_plus_d_ouvertures():
    peu = {"BTC": {"HL": 0.05, "Binance": 0.35}}
    beaucoup = {"BTC": {"HL": 0.05, "Binance": 0.35, "Bybit": 0.20, "OKX": 0.40}}
    assert compter_opportunites(beaucoup, cout_entree_bps=11.0) > compter_opportunites(peu, cout_entree_bps=11.0)
