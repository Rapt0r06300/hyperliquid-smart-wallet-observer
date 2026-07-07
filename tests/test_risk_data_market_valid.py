"""RISK (corrélation) + DATA (qualité) + MARKET (classes) + VALID (baselines)."""

from __future__ import annotations

from hl_observer.data_quality.guards import evaluate_data_quality, price_sanity, cross_source_agreement
from hl_observer.market.classification import MAJOR, LONG_TAIL, classify_market, thresholds_for_market
from hl_observer.risk.portfolio_correlation import (
    correlation_open_refusal, net_group_exposure, portfolio_concentration_report,
)
from hl_observer.validation.baselines import compare_to_baselines


def _pos(coin, side, notl):
    return {"coin": coin, "side": side, "notional_usdt": notl}


def test_correlation_detects_disguised_single_bet():
    # 3 alts L1 tous LONG = un seul pari directionnel
    positions = [_pos("SOL", "LONG", 40), _pos("AVAX", "LONG", 40), _pos("NEAR", "LONG", 40)]
    exp = net_group_exposure(positions)
    assert exp["l1_alts"] == 120.0
    rep = portfolio_concentration_report(positions)
    assert rep["directionality_ratio"] == 1.0  # tout dans le même sens
    assert rep["dominant_group"] == "l1_alts"


def test_correlation_refuses_redundant_position():
    positions = [_pos("SOL", "LONG", 40), _pos("AVAX", "LONG", 40), _pos("NEAR", "LONG", 40)]
    r = correlation_open_refusal(positions, coin="APT", side="LONG", new_notional_usdt=40, max_positions_per_group=3)
    assert r == "CORR_TOO_MANY_SAME_GROUP_SAME_SIDE"
    r2 = correlation_open_refusal(positions, coin="APT", side="LONG", new_notional_usdt=40, max_positions_per_group=5, max_group_net_exposure_usdt=120)
    assert r2 == "CORR_GROUP_NET_EXPOSURE_EXCEEDED"
    # un SHORT réduit l'exposition nette du groupe → autorisé
    assert correlation_open_refusal(positions, coin="APT", side="SHORT", new_notional_usdt=40, max_positions_per_group=5) == ""


def test_data_quality_blocks_fat_finger_and_contradiction():
    fat = price_sanity("HYPE", 200.0, [100.0, 101.0, 99.5, 100.5])
    assert fat["ok"] is False and fat["verdict"] == "PRICE_OUTLIER_FAT_FINGER"
    contra = cross_source_agreement("BTC", {"hl": 50_000.0, "bybit": 52_000.0}, max_disagreement_pct=1.5)
    assert contra["ok"] is False and contra["verdict"] == "SOURCES_CONTRADICT"
    verdict = evaluate_data_quality("HYPE", 200.0, [100.0, 101.0, 99.5], {"hl": 200.0, "bybit": 100.0}, 1000, 1500)
    assert verdict["tradeable"] is False
    assert "PRICE_OUTLIER_FAT_FINGER" in verdict["reasons"]


def test_data_quality_ok_on_clean_data():
    v = evaluate_data_quality("BTC", 50_050.0, [50_000, 50_100, 49_950, 50_020], {"hl": 50_050.0, "bybit": 50_040.0}, 1400, 1500)
    assert v["tradeable"] is True and v["verdict"] == "OK"


def test_market_classification_and_thresholds():
    assert classify_market(l2_depth_usdt=500_000, daily_volume_usdt=200_000_000) == MAJOR
    assert classify_market(l2_depth_usdt=5_000, daily_volume_usdt=500_000) == LONG_TAIL
    major = thresholds_for_market(l2_depth_usdt=500_000, daily_volume_usdt=200_000_000)
    tail = thresholds_for_market(l2_depth_usdt=5_000, daily_volume_usdt=500_000)
    assert major["min_edge_bps"] < tail["min_edge_bps"]      # long-tail exige plus d'edge
    assert major["max_notional_usdt"] > tail["max_notional_usdt"]  # plus petit sur long-tail


def test_baselines_answer_the_truth_question():
    # stratégie +5, no-trade 0, hold-BTC: prix +2% sur 1000 -> +20
    strat = [1000.0, 1002.0, 1005.0]
    prices = [100.0, 101.0, 102.0]
    cmp = compare_to_baselines(strat, starting_equity_usdt=1000.0, btc_prices=prices)
    assert cmp["beats_no_trade"] is True          # +5 > 0
    assert cmp["beats_hold_btc"] is False         # +5 < +20
    assert cmp["beats_both"] is False
    assert cmp["excess_vs_no_trade_usdt"] == 5.0
