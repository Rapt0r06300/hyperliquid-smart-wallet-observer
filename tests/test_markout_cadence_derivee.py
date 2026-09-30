"""B1 (V3 §3.1/§3.3) — le markout offline dérive sa tolérance de la CADENCE réelle du feed au lieu
du repli fixe 60 s, et refuse (None) tout horizon plus court que la cadence.

Vérité renforcée : impossible de mesurer un markout 5 s sur une bande allMids à ~16,7 s de cadence.
Ces tests prouvent que l'ancien appel (sans cadence) RENVOYAIT un chiffre (le faux-edge) là où le
neuf refuse honnêtement. L'end-to-end de `executer` reste couvert (sans régression) par
`tests/test_global_observer_pipeline.py`.
"""

import importlib

GOP = importlib.import_module("hl_observer.ops.global_observer_pipeline")


def _index(coin, points):
    pts = sorted(points)
    return {coin.upper(): {"ts": [int(t) for t, _ in pts], "mid": [float(m) for _, m in pts]}}


def test_cadence_mediane():
    idx = _index("BTC", [(0, 100.0), (500, 100.0), (1000, 100.0), (1500, 100.0)])
    assert GOP.cadence_ms_par_coin(idx)["BTC"] == 500.0


def test_cadence_indeterminable_un_seul_point():
    assert GOP.cadence_ms_par_coin(_index("BTC", [(0, 100.0)]))["BTC"] == 0.0


def test_markout_mesurable_si_cadence_fine():
    # feed 500 ms, horizon 5000 ms : mesurable ; +100 bps dans le sens long.
    pts = [(t, 100.0) for t in range(0, 5000, 500)] + [(5000, 101.0)]
    idx = _index("BTC", pts)
    cad = GOP.cadence_ms_par_coin(idx)["BTC"]
    m = GOP.markout_bps(idx, coin="BTC", ts_ms=0, sens=1, horizon_ms=5000, cadence_ms=cad)
    assert m is not None and round(m) == 100


def test_markout_non_mesurable_si_horizon_sous_cadence():
    # feed grossier 16 700 ms (allMids), horizon 5000 ms : NON mesurable -> None.
    idx = _index("BTC", [(0, 100.0), (16700, 101.0), (33400, 102.0)])
    cad = GOP.cadence_ms_par_coin(idx)["BTC"]
    assert cad == 16700.0
    assert GOP.markout_bps(idx, coin="BTC", ts_ms=0, sens=1, horizon_ms=5000, cadence_ms=cad) is None


def test_ancien_repli_60s_aurait_menti():
    # Sans cadence (ancien appel), la tolérance 60 s prend une cotation à 16,7 s pour un horizon 5 s.
    idx = _index("BTC", [(0, 100.0), (16700, 101.0)])
    ancien = GOP.markout_bps(idx, coin="BTC", ts_ms=0, sens=1, horizon_ms=5000)  # cadence_ms=None -> 60 s
    assert ancien is not None                     # l'ancien comportement renvoyait un chiffre (faux-edge)
    cad = GOP.cadence_ms_par_coin(idx)["BTC"]
    neuf = GOP.markout_bps(idx, coin="BTC", ts_ms=0, sens=1, horizon_ms=5000, cadence_ms=cad)
    assert neuf is None                           # le neuf refuse honnêtement


def test_latence_decale_la_fenetre():
    # §3.3 — mesurer depuis un instant d'entrée donné (ici ts=10000, après latence) ; feed fin, +300 bps.
    pts = [(t, 100.0) for t in range(0, 15000, 250)] + [(15000, 103.0)]
    idx = _index("BTC", pts)
    cad = GOP.cadence_ms_par_coin(idx)["BTC"]
    m = GOP.markout_bps(idx, coin="BTC", ts_ms=10000, sens=1, horizon_ms=5000, cadence_ms=cad)
    assert m is not None and round(m) == 300
