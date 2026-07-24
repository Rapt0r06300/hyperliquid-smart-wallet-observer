"""METAORDER_SHADOW_V1 (rectif Flo 24/07) — cœur PUR + runner injectable, sans réseau, sans position.

On teste : sens/maker-taker, index+étiquetage TWAP, détection de métaordres (regroupement + REVERSAL),
classement de stade, PnL forward net après coûts, placebo, OFI top-5, IC, lookup prix, la construction de
signaux bout-en-bout (3 âges séparés) et le runner `executer` (fournisseurs injectés) qui n'ouvre RIEN.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

M = importlib.import_module("hl_observer.experimental.metaorder_shadow")


def _f(side, time, sz=10.0, px=100.0, crossed=False, tid=None, hsh=None, coin="SOL"):
    return {"coin": coin, "side": side, "time": time, "sz": sz, "px": px,
            "crossed": crossed, "tid": tid, "hash": hsh}


def test_sens_et_maker_taker():
    assert M.sens_fill({"side": "B"}) == 1 and M.sens_fill({"side": "A"}) == -1 and M.sens_fill({}) == 0
    assert M.maker_taker({"crossed": True}) == "taker" and M.maker_taker({"crossed": False}) == "maker"


def test_index_et_etiquetage_twap():
    idx = M.index_twap([{"fill": {"tid": 11, "hash": "h1"}, "twapId": 7}])
    assert idx.get(11) == 7 and idx.get("h1") == 7
    assert M.est_twap({"tid": 11}, idx) is True and M.est_twap({"tid": 99, "hash": "hx"}, idx) is False
    assert M.est_twap({"tid": 1}, {}) is False                    # index vide -> jamais TWAP


def test_detecter_metaordres_regroupe_et_detecte_reversal():
    fills = [_f("B", 1000), _f("B", 2000), _f("B", 3000),          # 1 métaordre BUY (espacés < 60 s)
             _f("A", 4000)]                                        # inversion -> nouveau métaordre SELL (reversal)
    metas = M.detecter_metaordres(fills, intervalle_ms=60_000)
    assert len(metas) == 2 and metas[0]["sens"] == 1 and len(metas[0]["fills"]) == 3
    assert metas[1]["sens"] == -1 and metas[1]["reversal"] is True
    # un grand trou (> intervalle) coupe le métaordre même à sens égal
    m2 = M.detecter_metaordres([_f("B", 1000), _f("B", 1000 + 120_000)], intervalle_ms=60_000)
    assert len(m2) == 2 and m2[0]["reversal"] is False and m2[1]["reversal"] is False


def test_classer_stade():
    meta = {"reversal": False}
    assert M.classer_stade(0, 4, meta) == "FIRST_SLICE"
    assert M.classer_stade(1, 4, meta) == "CONTINUATION"
    assert M.classer_stade(3, 4, meta) == "LATE_STAGE"            # dernier
    assert M.classer_stade(0, 3, {"reversal": True}) == "REVERSAL"  # 1er slice d'un métaordre inverse


def test_pnl_forward_net_apres_couts():
    assert M.pnl_forward_net_bps(100.0, 101.0, 1, 16.0) == 84.0   # +100 bps bruts - 16 de coûts
    assert M.pnl_forward_net_bps(100.0, 101.0, -1, 16.0) == -116.0  # short : le hausse est contre nous
    assert M.pnl_forward_net_bps(100.0, None, 1, 16.0) is None    # pas de forward -> None (jamais inventé)


def test_placebo_separe_coin_et_marche():
    p = M.placebo_bps(100.0, 101.0, 50.0, 50.25, 1)              # coin +100 bps, marché(BTC) +50 bps
    assert p["ret_coin_bps"] == 100.0 and p["ret_marche_bps"] == 50.0 and p["alpha_vs_marche_bps"] == 50.0
    assert M.placebo_bps(0, 101, 50, 50, 1) is None              # coin illisible -> None


def test_ofi_top5():
    av = {"levels": [[{"px": "1", "sz": "50"}, {"px": "0.9", "sz": "50"}],
                     [{"px": "1.1", "sz": "60"}, {"px": "1.2", "sz": "40"}]]}
    ap = {"levels": [[{"px": "1", "sz": "100"}, {"px": "0.9", "sz": "50"}],
                     [{"px": "1.1", "sz": "50"}, {"px": "1.2", "sz": "40"}]]}
    # bids: 100+50-... dbid = (150-100)=50 ; dask = (90-100)=-10 ; OFI = 50 - (-10) = 60
    assert M.ofi_top5(av, ap) == 60.0
    assert M.ofi_top5({}, ap) is None


def test_ic_pearson_correlation_positive():
    sig = [{"taille_relative": 0.1, "pnl_net_bps": 1.0}, {"taille_relative": 0.2, "pnl_net_bps": 2.0},
           {"taille_relative": 0.3, "pnl_net_bps": 3.0}]
    assert M.ic_pearson(sig) == 1.0                               # relation parfaitement linéaire -> IC = 1
    assert M.ic_pearson(sig[:2]) is None                         # < 3 points -> None


def test_prix_au():
    serie = [(100, 1.0), (200, 2.0), (300, 3.0)]
    assert M.prix_au(serie, 250) == 2.0 and M.prix_au(serie, 1000) == 3.0
    assert M.prix_au(serie, 50) is None and M.prix_au([], 100) is None


def test_construire_signaux_bout_en_bout_trois_ages():
    H = 300_000
    fills = [_f("B", 1000, crossed=True, tid=1), _f("B", 2000, crossed=False, tid=2)]
    tape_coin = [(1000, 100.0), (2000, 100.0), (301000, 101.0), (302000, 101.0)]
    tape_btc = [(1000, 50.0), (301000, 50.25), (302000, 50.25)]
    sigs = M.construire_signaux(fills, idx_twap={}, tape_coin=tape_coin, tape_btc=tape_btc,
                                cout_ar_bps=16.0, horizon_ms=H, maintenant_ms=1_000_000)
    assert [s["stade"] for s in sigs] == ["FIRST_SLICE", "LATE_STAGE"]
    assert sigs[0]["maker_taker"] == "taker" and sigs[1]["maker_taker"] == "maker"
    assert sigs[0]["pnl_net_bps"] == 84.0 and sigs[0]["alpha_vs_marche_bps"] == 50.0   # +100 coin - 50 marché
    # TROIS ÂGES séparés : stade (depuis 1er slice), fill HL (skew), latence locale (N/A en shadow)
    assert sigs[0]["age_stade_ms"] == 0 and sigs[1]["age_stade_ms"] == 1000
    assert sigs[0]["age_fill_hl_ms"] == 1_000_000 - 1000 and sigs[0]["latence_locale_ms"] is None


def test_construire_signaux_sans_tape_ne_crashe_pas_et_pnl_none():
    sigs = M.construire_signaux([_f("B", 1000)], idx_twap={}, tape_coin=[], tape_btc=[], maintenant_ms=2000)
    assert len(sigs) == 1 and sigs[0]["pnl_net_bps"] is None      # pas de forward -> None, jamais inventé


def test_executer_runner_injecte_ecrit_ledger_et_n_ouvre_rien(tmp_path):
    now = 10_000_000
    fills = [_f("B", now - 400_000, crossed=True, tid=1, hsh="h1"),
             _f("B", now - 390_000, crossed=False, tid=2, hsh="h2")]
    tape = {"SOL": [(now - 400_000, 100.0), (now - 100_000, 101.0)],
            "BTC": [(now - 400_000, 50.0), (now - 100_000, 50.0)]}
    res = M.executer(tmp_path, ["0xVault"],
                     fills_provider=lambda v, s: fills,
                     twap_provider=lambda v, s: [{"fill": {"tid": 1, "hash": "h1"}, "twapId": 7}],
                     tape=tape, horizon_ms=300_000, maintenant_ms=now)
    assert res["n_signaux"] == 2 and res["n_appels_rest"] == 2
    lignes = (tmp_path / M.LEDGER_RELPATH).read_text(encoding="utf-8").splitlines()
    assert len(lignes) == 2
    d0 = json.loads(lignes[0])
    assert d0["shadow"] is True and d0["real_execution"] is False and d0["vault"] == "0xVault"
    assert d0["is_twap"] is True                                  # tid=1 étiqueté TWAP via l'index
    assert "FIRST_SLICE" in res["stats"]                         # stats par stade produites
    assert (tmp_path / M.STATS_RELPATH).exists()
