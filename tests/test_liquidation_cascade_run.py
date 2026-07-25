"""LIQUIDATION_CASCADE_RAPID_V1 — mesure de réversion post-liquidation, prouvé sur fixtures.

Prouve : FADE directionnel (SELL_OVERSHOOT → long → REVERSAL si le mid remonte), net = gross − coût A/R,
dédup en épisodes (coin+sens contigus), profit factor.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("liquidation_cascade_run", _ROOT / "tools" / "liquidation_cascade_run.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

T0 = 1_700_000_000_000


def test_fade_sell_overshoot_reversal():
    # SELL_OVERSHOOT : mark forcé SOUS l'oracle → on ACHÈTE (long) ; si le mid remonte → REVERSAL, gross>0
    ev = {"coin": "BTC", "t": T0, "mid": 100.0, "sens": "SELL_OVERSHOOT", "overshoot_bps": -120.0,
          "fwd": {15: 100.05, 30: 100.10, 60: 100.08, 120: 100.15}}
    m = M.mesurer(ev)
    h = m["par_horizon"]["30"]
    assert m["dir"] == 1 and h["type"] == "REVERSAL" and h["gross_bps"] > 0
    assert abs(h["net_bps"] - (h["gross_bps"] - M.COUT_AR_BPS)) < 1e-6      # net = gross − coût A/R


def test_buy_overshoot_short():
    ev = {"coin": "ETH", "t": T0, "mid": 100.0, "sens": "BUY_OVERSHOOT", "overshoot_bps": 120.0,
          "fwd": {15: 99.9, 30: 99.8, 60: 99.85, 120: 99.7}}
    m = M.mesurer(ev)
    assert m["dir"] == -1 and m["par_horizon"]["30"]["type"] == "REVERSAL"  # baisse après BUY overshoot = réversion


def test_episodes_dedup_coin_sens():
    e = lambda t, sens="SELL_OVERSHOOT": {"coin": "BTC", "t": t, "mid": 100.0, "sens": sens, "overshoot_bps": -50, "fwd": {}}
    eps = M.episodes_liq([e(T0), e(T0 + 500), e(T0 + 100000), e(T0 + 400, "BUY_OVERSHOOT")])
    # T0 et T0+500 (même coin+sens) = 1 épisode ; T0+100000 = 2e ; T0+400 BUY = sens différent = 3e
    assert len(eps) == 3


def test_profit_factor():
    assert M._pf([3.0, -1.0, 2.0, -1.0]) == 2.5 and M._pf([-1.0, -2.0]) == 0.0
