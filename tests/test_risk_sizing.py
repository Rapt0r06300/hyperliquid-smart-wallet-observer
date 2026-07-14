"""Tests du dimensionnement du risque (valeurs connues + propriétés)."""
from __future__ import annotations

from hl_observer.backtesting.risk_sizing import cvar, fractional_kelly, historical_var, vol_target_size


def test_fractional_kelly_known_value():
    # p=0.6, b=1 -> f*=0.6-0.4=0.2 ; demi-Kelly -> 0.1
    assert abs(fractional_kelly(0.6, 1.0, fraction=0.5) - 0.1) < 1e-9
    assert fractional_kelly(0.3, 1.0) == 0.0          # espérance négative -> 0


def test_vol_target_scales_inversely_with_vol():
    assert vol_target_size(0.1, 0.2, 1000) == 500.0
    assert vol_target_size(0.1, 0.4, 1000) == 250.0   # 2x plus volatil -> moitié taille
    assert vol_target_size(0.1, 0.0, 1000) == 0.0


def test_var_and_cvar():
    rets = [-0.10, -0.08, -0.05, -0.02, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05]
    v = historical_var(rets, alpha=0.1)
    c = cvar(rets, alpha=0.1)
    assert v > 0 and c > 0
    assert c >= v            # la perte moyenne de queue >= le VaR
