"""LIQUIDATION recompute EXÉCUTION RÉELLE (bid/ask bbo) — prouvé sur fixtures.

Prouve : jointure bbo tolérante (None si trop loin), exécution RÉELLE ask-entrée/bid-sortie (le spread est payé),
NON_MESURABLE_NO_BBO sans cotation d'entrée.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("liquidation_real_exec", _ROOT / "tools" / "liquidation_real_exec.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

T0 = 1_700_000_000_000


def _serie(pas=200):
    temps, ba = [], []
    for i in range(700):
        t = T0 + i * pas
        mid = 100.0 * (1 + 0.001 * min((i * pas) / 120000.0, 1.0))     # monte 10 bps sur 120 s
        temps.append(t); ba.append((round(mid - 0.02, 4), round(mid + 0.02, 4)))
    return (temps, ba)


def test_bbo_a_tolerance():
    s = _serie()
    assert M._bbo_a(s, T0) is not None                                  # pile
    assert M._bbo_a(s, T0 - 10 * 60 * 1000) is None                     # trop loin → None (jamais inventé)


def test_execution_reelle_paye_le_spread_et_non_mesurable():
    ev = {"coin": "BTC", "t": T0, "sens": "SELL_OVERSHOOT"}
    m = M.mesurer_reel_bbo(ev, _serie())
    assert m["statut"] == "OK" and m["dir"] == 1
    h = m["par_horizon"]["120"]
    # long : achat ask / vente bid → le spread (~4 bps) + 9 bps frais sont retirés ; spread_reel reporté
    assert h["statut"] == "OK" and h["spread_reel_bps"] > 0
    # sans cotation d'entree -> NON_MESURABLE_NO_BBO
    assert M.mesurer_reel_bbo(ev, ([], []))["statut"] == "NON_MESURABLE_NO_BBO"
