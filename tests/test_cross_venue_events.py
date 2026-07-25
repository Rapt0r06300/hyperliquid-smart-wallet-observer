"""RAPID_ALPHA_SHADOW — analyseur EVENT-DRIVEN cross-venue (rectif Flo 25/07), prouvé sur fixtures.

Prouve : détection des 3 familles de choc, markout HL après latence RÉELLE + coûts HL seuls, NON_MESURABLE
sans cotation fraîche, décomposition des coûts, décision DISCOVERY_PROBE 2 fenêtres, pré-registration ≤12.
Aucun réseau, aucune donnée réelle requise.
"""
from __future__ import annotations

from hl_observer.experimental import cross_venue_events as C

T0 = 1_700_000_000_000


def _bt_avec_saut():
    """bookTicker Binance : mid 100 plat, puis saut à 100.2 (+20 bps)."""
    bt = [(T0 + i * 100, 99.99, 100.01) for i in range(15)]
    bt += [(T0 + 1500 + i * 100, 100.19, 100.21) for i in range(15)]
    return bt


def test_detecter_price_shock():
    chocs = C.detecter_chocs(_bt_avec_saut(), [], w_ms=1000.0, seuil_bps=8.0,
                             seuil_imb_usd=1e9, seuil_burst_usd=1e9)
    ps = [c for c in chocs if c["famille"] == "PRICE_SHOCK"]
    assert ps and ps[0]["dir"] == 1 and ps[0]["ampleur"] >= 8.0


def test_detecter_imbalance_et_burst():
    agg = [(T0 + i * 50, 100.0, 60.0, "buy") for i in range(40)]        # ~ 40×6000$ = 240k$ achat taker
    chocs = C.detecter_chocs([], agg, w_ms=1000.0, seuil_bps=1e9,
                             seuil_imb_usd=50_000.0, seuil_burst_usd=100_000.0)
    familles = {c["famille"] for c in chocs}
    assert "AGG_IMBALANCE" in familles and "TAKER_BURST" in familles
    assert all(c["dir"] == 1 for c in chocs)                            # achat → dir +1


def test_mesurer_markout_et_non_mesurable():
    t_choc = T0 + 2000
    hl = C._serie_hl([(t_choc + i * 100, 100.0 * (1 + 0.01 * min((i * 100) / 5000.0, 1.0)) - 0.01,
                       100.0 * (1 + 0.01 * min((i * 100) / 5000.0, 1.0)) + 0.01) for i in range(61)])
    choc = {"t": t_choc, "dir": 1, "famille": "PRICE_SHOCK", "ampleur": 20.0}
    m = C.mesurer_choc(choc, hl, latence_ms=400.0, fee_ar_bps=9.0)
    assert m["statut"] == "OK" and m["latence_reelle_ms"] >= 400
    h1 = m["par_horizon"]["1000"]
    assert h1["statut"] == "OK" and h1["gross_bps"] > 0 and h1["net_bps"] > 0     # HL suit → net positif
    assert "cout_ar_bps" in h1["cout"] and h1["cout"]["frais_ar"] == 9.0
    # aucune cotation HL → NON_MESURABLE (jamais inventé)
    vide = C.mesurer_choc(choc, C._serie_hl([]), latence_ms=400.0)
    assert vide["statut"] == "NON_MESURABLE"


def test_cout_decompose_somme():
    c = C.cout_hl_ar_bps(4.0, 4.0, 9.0, 1.0, 1.0)
    assert abs(c["cout_ar_bps"] - (2.0 + 2.0 + 9.0 + 1.0 + 1.0)) < 1e-9


def _mesure(t, net):
    return {"statut": "OK", "t_choc": t, "par_horizon": {"1000": {"statut": "OK", "net_bps": net}}}


def test_deux_fenetres_probe_armable_et_refus():
    pos = [_mesure(T0 + i * 1000, 5.0 + (i % 3)) for i in range(50)]     # 50 chocs, tous net>0, peu concentrés
    d = C.deux_fenetres(pos, 1000, min_chocs=20)
    assert d["probe_armable"] is True and d["fenetre_A"]["ok"] and d["fenetre_B"]["ok"]
    peu = [_mesure(T0 + i * 1000, 5.0) for i in range(10)]               # trop peu → refus
    assert C.deux_fenetres(peu, 1000, min_chocs=20)["probe_armable"] is False


def test_preregistration_max_12_uniques():
    p = C.preregistration()
    assert len(p) <= 12 and len({v["variante_id"] for v in p}) == len(p)
    assert {v["famille"] for v in p} == set(C.FAMILLES)
