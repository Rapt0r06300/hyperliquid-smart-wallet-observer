"""Calibration algorithmique des barrières: vol-scaling + espérance nette correcte."""

from __future__ import annotations

import math

from hl_observer.paper_trading import barrier_calibration as bc


def test_realized_range_bps_basic():
    # 100 -> 101 = +100 bps de range sur le dernier
    assert abs(bc.realized_range_bps([100.0, 101.0, 100.5]) - (1.0 / 100.5 * 10000)) < 1e-6
    assert bc.realized_range_bps([100.0]) is None  # pas assez de points


def test_per_coin_ranges_separates_calm_and_volatile():
    marks = []
    t = 1_000_000.0
    for i in range(10):
        marks.append({"ts": t + i, "coin": "ETH", "mid": 2500.0 + (i % 2)})   # ~0.4 bps
        marks.append({"ts": t + i, "coin": "KAITO", "mid": 0.80 + 0.02 * (i % 2)})  # ~250 bps
    r = bc.per_coin_median_range_bps(marks, window_s=900.0, min_obs=5)
    assert r["KAITO"] > r["ETH"] * 20  # le volatil a une range bien plus grande


def test_expectancy_and_breakeven_are_consistent():
    tp, sl, c = 120.0, 60.0, 12.0
    p_star = bc.breakeven_winrate(tp, sl, c)
    # au winrate d'équilibre, l'espérance est ~0
    assert abs(bc.expectancy_bps(p_star, tp, sl, c)) < 1e-6
    # au-dessus: positif ; en dessous: négatif
    assert bc.expectancy_bps(p_star + 0.1, tp, sl, c) > 0
    assert bc.expectancy_bps(p_star - 0.1, tp, sl, c) < 0


def test_recommend_barriers_favorable_rr_positive_expectancy():
    r = bc.recommend_barriers(30.0, k_sl=2.0, k_tp=4.0, cost_bps=12.0, assumed_winrate=0.55)
    assert r.base_stop_loss_bps == 60.0 and r.base_take_profit_bps == 120.0  # k×ref
    assert r.base_trailing_bps > 0 and r.base_trailing_activation_bps > r.base_trailing_bps
    assert r.breakeven_winrate < 0.45          # R:R 2:1 => seuil bas atteignable
    assert r.expectancy_bps_at_assumed > 0     # espérance nette positive à 55%
    env = r.env()
    assert env["HYPERSMART_V26_VOL_BARRIERS"] == "1"
    assert float(env["HYPERSMART_SLTP_TAKE_PROFIT_BPS"]) == 120.0


def test_calibrate_ref_range_falls_back_when_thin():
    # trop peu de coins -> fallback honnête (on ne calibre pas sur du vent)
    assert bc.calibrate_ref_range_bps([{"ts": 1, "coin": "ETH", "mid": 2500}], fallback=40.0) == 40.0
