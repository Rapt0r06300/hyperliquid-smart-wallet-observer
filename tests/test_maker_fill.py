"""Tests de la simulation d'entree MAKER sur chemins de prix reels (purs, deterministes)."""
from __future__ import annotations

from hl_observer.backtesting.maker_fill import (
    eval_maker_trades,
    find_maker_fill,
    maker_limit_price,
)
from hl_observer.backtesting.scenario_grid import Scenario


def _sc(**kw):
    d = dict(name="t", sl_bps=126.0, tp_bps=40.0, trailing_stop_bps=0.0, trailing_activation_bps=0.0,
             breakeven_bps=0.0, horizon_min=480.0, cost_bps=6.0, min_edge_bps=0.0, source="test",
             max_signal_age_ms=0.0, min_liquidity_score=0.0, min_consensus_wallets=1,
             max_copy_degradation_bps=0.0, min_leader_score=0.0, side_mode="both", catastrophic_stop_bps=180.0)
    d.update(kw)
    return Scenario(**d)


def test_limit_price_is_passive():
    assert maker_limit_price("LONG", 100.0, 5.0) == 100.0 * (1 - 0.0005)   # achat sous le mid
    assert maker_limit_price("SHORT", 100.0, 5.0) == 100.0 * (1 + 0.0005)  # vente au-dessus


def test_find_fill_touches_and_misses():
    # LONG limite 99.95 : remplie si le prix DESCEND la toucher
    path_dip = [(1000, 100.0), (1005, 99.90), (1010, 101.0)]
    assert find_maker_fill("LONG", 99.95, path_dip, 1000, 60000) == (1005, 99.95)
    # LONG : si le prix ne fait que monter -> jamais rempli (le gagnant a file)
    path_up = [(1000, 100.0), (1005, 100.3), (1010, 101.0)]
    assert find_maker_fill("LONG", 99.95, path_up, 1000, 60000) is None
    # hors fenetre -> pas de fill
    assert find_maker_fill("LONG", 99.95, [(1000, 100.0), (99000, 99.0)], 1000, 60000) is None


def test_eval_maker_measures_fill_and_adverse_selection():
    marks = {
        # AAA descend toucher la limite puis monte -> REMPLI + gagnant
        "AAA": [(1000, 100.0), (1005, 99.90), (1010, 100.6), (1020, 101.0), (1030, 101.5)],
        # BBB ne fait que monter -> NON rempli, mais le taker aurait gagne (selection adverse)
        "BBB": [(1000, 100.0), (1005, 100.3), (1010, 100.8), (1020, 101.2), (1030, 101.6)],
    }
    cands = [
        dict(coin="AAA", direction="LONG", current_mid=100.0, recorded_at=1000.0,
             edge_remaining_bps=50.0, copy_degradation_bps=3.0),
        dict(coin="BBB", direction="LONG", current_mid=100.0, recorded_at=1000.0,
             edge_remaining_bps=50.0, copy_degradation_bps=3.0),
    ]
    res = eval_maker_trades(_sc(), cands, marks, 500.0, offset_bps=5.0, window_ms=60000.0, maker_cost_bps=2.0)
    assert res["n_eligible"] == 2
    assert len(res["filled"]) == 1 and res["filled"][0] > 0      # AAA rempli et gagnant
    assert len(res["missed_taker"]) == 1 and res["missed_taker"][0] > 0  # BBB rate = gagnant manque
