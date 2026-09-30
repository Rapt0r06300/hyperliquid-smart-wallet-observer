"""
Tests de la qualité des leaders (sélectivité extrême / leaders prouvés gagnants).

100% pur, déterministe, sans réseau. READ-ONLY / PAPER-ONLY.
"""

from __future__ import annotations

from types import SimpleNamespace

from hyper_smart_observer.dydx_v4.leader_quality import (
    LeaderThresholds,
    any_track_record,
    count_proven,
    has_track_record,
    qualifies_as_leader,
)


def _w(addr, winrate, pf, trades):
    return SimpleNamespace(address=addr, winrate=winrate, profit_factor=pf, trade_count=trades)


def test_qualifies_as_leader_pass_and_fail():
    assert qualifies_as_leader(0.50, 1.5, 20) is True
    assert qualifies_as_leader(0.50, 1.5, 10) is False    # trop peu de trades
    assert qualifies_as_leader(0.30, 1.5, 20) is False    # winrate trop bas
    assert qualifies_as_leader(0.50, 1.0, 20) is False    # profit factor trop bas
    assert qualifies_as_leader(None, None, None) is False  # inconnu -> non prouvé


def test_custom_thresholds():
    th = LeaderThresholds(min_winrate=0.6, min_profit_factor=2.0, min_trades=30)
    assert qualifies_as_leader(0.65, 2.1, 40, th) is True
    assert qualifies_as_leader(0.55, 2.1, 40, th) is False


def test_has_track_record():
    assert has_track_record(_w("a", 0.5, 1.5, 12)) is True
    assert has_track_record(_w("a", 0.0, 1.0, 0)) is False


def test_count_proven():
    proven = _w("p1", 0.55, 1.6, 25)
    proven2 = _w("p2", 0.48, 1.4, 18)
    weak = _w("w1", 0.20, 0.8, 40)
    unscored = _w("u1", 0.0, 1.0, 0)
    score_by_addr = {w.address: w for w in [proven, proven2, weak, unscored]}
    n = count_proven(["p1", "p2", "w1", "u1", "missing"], score_by_addr)
    assert n == 2


def test_any_track_record():
    assert any_track_record([_w("a", 0, 1, 0), _w("b", 0.5, 1.5, 12)]) is True
    assert any_track_record([_w("a", 0, 1, 0), _w("b", 0, 1, 0)]) is False
    assert any_track_record([]) is False
