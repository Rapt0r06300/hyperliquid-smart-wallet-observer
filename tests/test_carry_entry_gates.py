"""Gates & throttle carry — spread serré exigé, convergence de base comme 2e PnL, veille si zéro edge."""
from __future__ import annotations

from hl_observer.funding.carry_entry_gates import doit_throttler, gain_convergence_base_bps, spread_assez_serre


def test_spread_serre_exige_connu():
    assert spread_assez_serre(3.0, 1.0) is True
    assert spread_assez_serre(9.0, 2.0) is False           # combiné 11 > 8
    assert spread_assez_serre(None, 1.0) is False          # inconnu -> refus (on ne devine pas)


def test_convergence_base_2e_pnl():
    assert gain_convergence_base_bps(None, 11.0) is None
    assert gain_convergence_base_bps(4.0, 11.0) is None     # 4×0.5=2 < mini 5 -> pas viable
    g = gain_convergence_base_bps(60.0, 11.0)               # 60×0.5=30 capturable - 11 = 19 net
    assert g is not None and abs(g - 19.0) < 1e-9


def test_throttle_seulement_si_tout_a_zero():
    assert doit_throttler(carrys_viables=0, purges_actives=0, edge_copy_bps=0.0) is True
    assert doit_throttler(carrys_viables=2, purges_actives=0, edge_copy_bps=None) is False   # carry actif
    assert doit_throttler(carrys_viables=0, purges_actives=1, edge_copy_bps=None) is False   # purge active
