"""Recherche massive: split temporel, gagnant robuste out-of-sample, cout reel. REPLAY-only."""

from __future__ import annotations

from hl_observer.backtesting.ab_flag_replay import marks_by_coin
from hl_observer.backtesting.scenario_grid import _mk, archetype_scenarios
from hl_observer.backtesting.scenario_search import (
    eval_trades, report_from_trades, search, temporal_split,
)


def _uptrend_marks(n=150, coin="AAA", start=100.0, step=0.5, t0=1000.0):
    return [{"ts": t0 + i * 10.0, "coin": coin, "mid": start + i * step} for i in range(n)]


def _long_candidates(n=30, coin="AAA", t0=1000.0):
    return [
        {"coin": coin, "direction": "LONG", "edge_remaining_bps": 50.0,
         "current_mid": 100.0 + (i * 40.0 / 10.0) * 0.5, "recorded_at": t0 + i * 40.0,
         "leader_notional_usdt": 50.0, "leader_score": 80.0,
         "copy_degradation_bps": 5.0, "liquidity_score": 0.8}
        for i in range(n)
    ]


def test_temporal_split_is_chronological():
    tr, te = temporal_split([{"recorded_at": 3}, {"recorded_at": 1}, {"recorded_at": 2}], 0.7)
    assert [x["recorded_at"] for x in tr] == [1, 2]
    assert [x["recorded_at"] for x in te] == [3]


def _scenarios_horizon_court():
    """🔴 #410 / H-05 — LA PURGE A CHANGE CE TEST, ET ELLE AVAIT RAISON.

    Ce decor tient sur **20 minutes** (30 candidats espaces de 40 s). Or `archetype_scenarios()`
    contient des horizons jusqu'a **8 HEURES**. La purge vidait donc le train -- **et c'etait
    juste** : *on ne peut pas evaluer honnetement une strategie a 8 h d'horizon sur 20 minutes de
    donnees.* Le test d'avant ne « marchait » que parce que la coupe FUYAIT.

    ⚠️ ET C'EST UN AVERTISSEMENT REEL, PAS UN DETAIL DE TEST : nos vraies donnees ne couvrent que
    ~19 h. Avec des horizons de 8 h, la purge mange l'essentiel du train. **La recherche sur
    150 M de scenarios n'a jamais ete statistiquement saine avec cette duree d'historique.**
    C'est le meme mur que partout : *data-limited*.

    On donne donc a ce test des horizons compatibles avec SES donnees (2-3 min).
    """
    return [
        _mk("court_a", 60, 90, 0, 0, 0, 2.0, 6.0, 20.0, "test"),
        _mk("court_b", 80, 120, 0, 0, 0, 3.0, 6.0, 20.0, "test"),
        _mk("court_c", 50, 150, 0, 0, 0, 2.5, 6.0, 20.0, "test"),
    ]


def test_winner_survives_out_of_sample_on_uptrend():
    scen = _scenarios_horizon_court()
    rep = search(_long_candidates(30), _uptrend_marks(150), scen,
                 train_frac=0.6, top_k=8, min_trades=3, jobs=1)
    assert rep["scenarios_evaluated"] == len(scen)
    assert rep["train_size"] > 0 and rep["test_size"] > 0
    # la coupe DIT ce qu'elle a purge -- une purge silencieuse serait inutile
    assert rep["coupe_purgee"]["n_purges"] >= 0
    assert rep["coupe_purgee"]["horizon_min"] == 3.0        # le PIRE horizon de la grille
    assert len(rep["finalists"]) >= 1
    top = rep["finalists"][0]
    assert (top["train"]["net_total_usd"] or 0.0) > 0.0
    assert (top["test"]["net_total_usd"] or 0.0) > 0.0
    assert "aucune promesse" in rep["honesty"]


def test_finalists_ranked_by_oos_net():
    rep = search(_long_candidates(30), _uptrend_marks(150), archetype_scenarios(),
                 train_frac=0.6, top_k=8, min_trades=3, jobs=1)
    nets = [f["test"]["net_total_usd"] or 0.0 for f in rep["finalists"]]
    assert nets == sorted(nets, reverse=True)


def test_higher_cost_reduces_net():
    mbc = marks_by_coin(_uptrend_marks(150))
    cands = _long_candidates(30)
    lo = _mk("lo", 40, 80, 0, 0, 0, 240, 5, 0, "t")
    hi = _mk("hi", 40, 80, 0, 0, 0, 240, 200, 0, "t")
    net_lo = report_from_trades(eval_trades(lo, cands, mbc))["net_total_usd"]
    net_hi = report_from_trades(eval_trades(hi, cands, mbc))["net_total_usd"]
    assert net_hi < net_lo
