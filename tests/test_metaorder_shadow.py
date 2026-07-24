"""METAORDER_SHADOW_V1 (révision statistique, rectif Flo 24/07) — cœur PUR + runner injectable, sans réseau.

On teste : dédup + metaorder_id STABLE, détection/stades, coût L2 réel par signal, bootstrap CLUSTERISÉ par
métaordre (pas d'IC par slice), walk-forward purgé, stats par stade avec n_métaordres UNIQUES, groupements,
et le runner `executer` (fournisseurs injectés) — budget REST EXACT, statut TWAP, n'ouvre RIEN.
"""
from __future__ import annotations

import importlib
import json

M = importlib.import_module("hl_observer.experimental.metaorder_shadow")


def _f(side, time, sz=10.0, px=100.0, crossed=False, tid=None, hsh=None, coin="SOL", oid=None):
    return {"coin": coin, "side": side, "time": time, "sz": sz, "px": px,
            "crossed": crossed, "tid": tid, "hash": hsh, "oid": oid}


def test_dedup_et_metaorder_id_stable():
    a = _f("B", 1000, tid=1, hsh="h1")
    fs = M.dedup_fills([a, dict(a), _f("B", 2000, tid=2, hsh="h2")])
    assert len(fs) == 2                                          # doublon (même clé composite) retiré
    i1 = M.metaorder_id("0xV", "SOL", 1, 1000)
    assert i1 == M.metaorder_id("0xV", "SOL", 1, 1000) and i1 != M.metaorder_id("0xV", "SOL", -1, 1000)


def test_detecter_metaordres_regroupe_et_reversal():
    metas = M.detecter_metaordres([_f("B", 1000), _f("B", 2000), _f("A", 3000)], intervalle_ms=60_000)
    assert len(metas) == 2 and len(metas[0]["fills"]) == 2 and metas[1]["reversal"] is True


def test_classer_stade():
    assert M.classer_stade(0, 4, {"reversal": False}) == "FIRST_SLICE"
    assert M.classer_stade(1, 4, {"reversal": False}) == "CONTINUATION"
    assert M.classer_stade(3, 4, {"reversal": False}) == "LATE_STAGE"
    assert M.classer_stade(0, 2, {"reversal": True}) == "REVERSAL"


def test_cout_l2_reel_vs_screening():
    l2 = {"hl_bid": 99.9, "hl_ask": 100.1, "depth_usd": 100_000.0}   # spread ~20 bps
    bps, src = M.cout_l2_reel_bps(l2, 1000.0)
    assert src == "l2_courant_par_taille" and bps > M.FRAIS_TAKER_BPS   # inclut le spread + slippage
    assert M.cout_l2_reel_bps(None, 1000.0) == (M.COUT_AR_DEFAUT_BPS, "screening_16bps")   # fallback screening


def test_pnl_net_et_placebo():
    assert M.pnl_forward_net_bps(100.0, 101.0, 1, 16.0) == 84.0
    p = M.placebo_bps(100.0, 101.0, 50.0, 50.25, 1)
    assert p["ret_coin_bps"] == 100.0 and p["alpha_vs_marche_bps"] == 50.0


def test_bootstrap_clusterise_respecte_les_clusters():
    paires = [("mo1", 1.0), ("mo1", 1.0), ("mo2", 3.0), ("mo2", 3.0)]
    r = M.bootstrap_clusterise(paires, n=500, seed=1)
    assert r["moy"] == 2.0 and r["n_clusters"] == 2 and r["ic_bas"] is not None and 1.0 <= r["ic_haut"] <= 3.0
    # UN seul cluster -> PAS d'IC (on refuse de fabriquer une significativité sur des points dépendants)
    r1 = M.bootstrap_clusterise([("mo1", 1.0), ("mo1", 2.0)], n=100)
    assert r1["n_clusters"] == 1 and r1["ic_bas"] is None


def test_walk_forward_purge_decoupe_le_temps():
    sig = [{"fill_time": t, "stade": "FIRST_SLICE", "pnl_net_bps": 1.0} for t in range(0, 12_000_000, 1_000_000)]
    wf = M.walk_forward_purge(sig, n_folds=3, horizon_ms=300_000)
    assert wf["n_folds"] == 3 and len(wf["folds"]) == 3 and all("par_stade" in f for f in wf["folds"])


def test_construire_signaux_metaorder_cout_et_trois_ages():
    fills = [_f("B", 1000, crossed=True, tid=1), _f("B", 2000, crossed=False, tid=2)]
    tape_coin = [(1000, 100.0), (301000, 101.0), (302000, 101.0)]
    sigs = M.construire_signaux(fills, vault="0xV", idx_twap={}, tape_coin=tape_coin, tape_btc=[],
                                cout_fn=lambda c, t: (10.0, "l2_courant_par_taille"),
                                horizon_ms=300_000, maintenant_ms=1_000_000)
    assert [s["stade"] for s in sigs] == ["FIRST_SLICE", "LATE_STAGE"]
    assert sigs[0]["metaorder_id"] == sigs[1]["metaorder_id"]     # même métaordre parent
    assert sigs[0]["cout_ar_bps"] == 10.0 and sigs[0]["pnl_net_bps"] == 90.0   # +100 bruts - 10 de coût L2
    assert sigs[0]["age_stade_ms"] == 0 and sigs[1]["age_stade_ms"] == 1000    # âge du stade
    assert sigs[0]["age_fill_hl_ms"] == 999_000 and sigs[0]["latence_locale_ms"] is None
    assert sigs[0]["jour"] == 1000 // 86_400_000


def test_stats_par_stade_compte_metaordres_uniques():
    sig = []
    for mo in ("mo1", "mo2"):
        sig.append({"metaorder_id": mo, "stade": "FIRST_SLICE", "pnl_net_bps": -30.0, "alpha_vs_marche_bps": -5.0,
                    "taille_usd": 1000.0, "maker_taker": "taker", "is_twap": False, "cout_ar_bps": 16.0,
                    "cout_source": "screening_16bps"})
        for _ in range(3):                                       # 3 slices CONTINUATION par métaordre
            sig.append({"metaorder_id": mo, "stade": "CONTINUATION", "pnl_net_bps": -10.0,
                        "alpha_vs_marche_bps": -1.0, "taille_usd": 500.0, "maker_taker": "maker",
                        "is_twap": False, "cout_ar_bps": 16.0, "cout_source": "screening_16bps"})
    st = M.stats_par_stade(sig, n_boot=300)
    assert st["FIRST_SLICE"]["n_slices"] == 2 and st["FIRST_SLICE"]["n_metaordres"] == 2
    assert st["CONTINUATION"]["n_slices"] == 6 and st["CONTINUATION"]["n_metaordres"] == 2   # 6 slices, 2 métaordres
    assert st["CONTINUATION"]["pnl_net_bps_moy"] == -10.0 and "cout_sources" in st["CONTINUATION"]


def test_agreger_par_vault():
    sig = [{"vault": "0xA", "metaorder_id": "m1", "pnl_net_bps": -5.0},
           {"vault": "0xB", "metaorder_id": "m2", "pnl_net_bps": 5.0}]
    g = M.agreger_par(sig, "vault")
    assert g["0xA"]["n_metaordres"] == 1 and g["0xB"]["pnl_net_bps_moy"] == 5.0


def _book(mid_spread=20.0):
    # carnet symétrique autour de mid=100, spread=mid_spread bps, 1000 unités par niveau
    demi = mid_spread / 2.0 / 1e4 * 100.0
    return {"levels": [[{"px": str(100 - demi), "sz": "1000"}, {"px": str(100 - demi - 0.1), "sz": "1000"}],
                       [{"px": str(100 + demi), "sz": "1000"}, {"px": str(100 + demi + 0.1), "sz": "1000"}]]}


def test_vwap_slippage_et_composants_separes():
    b = _book(20.0)                                              # spread 20 bps, mid 100
    vwap, slip, filled, complet = M.vwap_slippage(b, 100.0, 1)   # petit achat -> au touch
    assert complet is True and abs(slip - 10.0) < 0.5            # slippage ~ demi-spread (touch)
    cc = M.cout_composants(b, 100.0, 1, 9.0)
    assert abs(cc["spread_bps"] - 20.0) < 0.5 and cc["slippage_vwap_bps"] == 0.0 and cc["fee_bps"] == 9.0
    assert abs(cc["cout_ar_bps"] - 29.0) < 0.5                   # spread(20) + slippage(0) + frais(9)
    # notional qui dépasse le 1er niveau -> slippage VWAP > 0
    assert M.cout_composants(b, 150_000.0, 1, 9.0)["slippage_vwap_bps"] > 0
    # profondeur insuffisante -> flag False
    assert M.vwap_slippage(b, 10_000_000.0, 1)[3] is False


def test_courbe_edge_cout_capacite_L2_vraie():
    b = _book(20.0)
    sig = [{"stade": "LATE_STAGE", "metaorder_id": "m%d" % i, "coin": "SOL", "sens": 1, "ret_coin_bps": 40.0}
           for i in range(3)]                                    # gross +40 bps, coût ~29 -> net ~+11
    c = M.courbe_edge_cout(sig, {"SOL": b}, fee_ar_bps=9.0, n_boot=200)["LATE_STAGE"]
    assert c["courbe"]["100"]["net_moy_bps"] > 0 and c["courbe"]["100"]["spread_moy_bps"] > 0
    assert c["capacite_usd_edge_positif"] == 500.0              # net>0 jusqu'à 500 $ -> capacité = 500
    # gross négatif -> aucune capacité
    sign = [{"stade": "LATE_STAGE", "metaorder_id": "m%d" % i, "coin": "SOL", "sens": 1, "ret_coin_bps": -5.0} for i in range(3)]
    assert M.courbe_edge_cout(sign, {"SOL": b}, fee_ar_bps=9.0, n_boot=200)["LATE_STAGE"]["capacite_usd_edge_positif"] == 0.0


def test_comparer_executions_passif_fill_miss_sans_fill_fictif():
    b = _book(20.0)
    sig = {"sens": 1, "fill_time": 1000, "coin": "SOL"}
    tape_fill = [(1000, 100.0), (2000, 99.9), (301000, 100.5)]   # descend au bid (99.9) -> fill passif
    r = M.comparer_executions(sig, tape_fill, b, fee_taker_ar_bps=9.0, fee_maker_ar_bps=9.0,
                              notional_usd=100.0, horizon_ms=300_000, fenetre_passif_ms=60_000)
    assert r["taker_immediat"] is not None and r["no_trade"] == 0.0
    assert r["limite_passive"]["rempli"] is True and r["limite_passive"]["delai_ms"] == 1000
    assert r["limite_passive"]["queue_devant_usd"] > 0
    tape_miss = [(1000, 100.0), (2000, 100.2), (301000, 100.5)]   # ne redescend jamais au bid -> MISS
    r2 = M.comparer_executions(sig, tape_miss, b, fee_taker_ar_bps=9.0, fee_maker_ar_bps=9.0,
                               notional_usd=100.0, horizon_ms=300_000, fenetre_passif_ms=60_000)
    assert r2["limite_passive"]["rempli"] is False                # aucun fill fictif


def test_preregistration_gelee_une_seule_fois(tmp_path):
    p1 = M.write_preregistration(tmp_path)
    d = json.loads(p1.read_text(encoding="utf-8"))
    assert d["hypothese_unique"]["stades"] == ["CONTINUATION", "LATE_STAGE"]
    assert "OFI" in d["hypothese_unique"]["filtre"] and "walk-forward" in d["regle_validation"]
    t0 = d["gele_le_ts_ms"]
    M.write_preregistration(tmp_path)                            # 2e appel : NE réécrit PAS (anti-retune)
    assert json.loads(p1.read_text(encoding="utf-8"))["gele_le_ts_ms"] == t0


def test_executer_runner_injecte_courbe_execs_prereg_et_n_ouvre_rien(tmp_path):
    now = 10_000_000
    fills = [_f("B", now - 400_000, tid=1, hsh="h1"), _f("B", now - 390_000, tid=2, hsh="h2")]
    tape = {"SOL": [(now - 400_000, 100.0), (now - 100_000, 101.0)], "BTC": [(now - 400_000, 50.0)]}
    res = M.executer(tmp_path, ["0xVault"],
                     fills_provider=lambda v, s: fills,
                     twap_provider=lambda v, s: [{"fill": {"tid": 1, "hash": "h1"}, "twapId": 7}],
                     book_provider=lambda c: _book(20.0),
                     tape=tape, horizon_ms=300_000, maintenant_ms=now)
    assert res["n_signaux"] == 2 and res["n_metaordres"] == 1
    # budget EXACT : userFillsByTime(2)=20 + userTwapSliceFills(1)=20 + l2Book=2 -> 42
    assert res["poids_passe"] == 42 and res["n_appels"] == 3
    stats = json.loads((tmp_path / M.STATS_RELPATH).read_text(encoding="utf-8"))
    assert "courbe_edge_cout_par_notional" in stats and "execution_comparee_continuation_late" in stats
    assert stats["twap_statut_par_vault"].get("couvert_avec_twap") == 1
    assert (tmp_path / M.PREREG_RELPATH).exists()               # pré-enregistrement écrit
    assert json.loads(lines_first(tmp_path))["real_execution"] is False


def lines_first(tmp_path):
    return (tmp_path / M.LEDGER_RELPATH).read_text(encoding="utf-8").splitlines()[0]
