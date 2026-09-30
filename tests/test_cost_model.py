"""Tests du modèle de coûts (paliers, override, latence)."""
from __future__ import annotations

from hl_observer.backtesting.cost_model import apply_latency, cost_bps_for


def test_cost_tiers_by_liquidity():
    assert cost_bps_for("BTC", liquidity_score=0.9) < cost_bps_for("XYZ", liquidity_score=0.5)
    assert cost_bps_for("ANY") == 6.0                       # défaut sans info


def test_cost_override_wins():
    assert cost_bps_for("BTC", liquidity_score=0.9, overrides={"BTC": 2.0}) == 2.0


def test_apply_latency_delays_entry():
    path = [(1000.0, 100.0), (1005.0, 100.5), (1010.0, 101.0), (1020.0, 101.5)]
    # signal à 1000, latence 7000ms -> 1er point à ts>=8000... aucun -> None
    assert apply_latency(1000.0, path, latency_ms=7000.0) is None
    # signal à 1000, latence 6ms -> 1er point à ts>=1006 = (1010,101.0)
    assert apply_latency(1000.0, path, latency_ms=6.0) == (1010.0, 101.0)
