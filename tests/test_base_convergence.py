"""A5 — convergence de base : le 2e PnL, et la correction honnete du credit de base optimiste."""
from __future__ import annotations

import pytest

from hl_observer.funding.base_convergence import (
    capture_base_bps, correction_sortie_bps, base_convergee,
)


def test_capture_positive_quand_le_spread_se_resserre():
    # entree base +10, sortie base +2 -> on a capture 8 bps
    assert capture_base_bps(10.0, 2.0) == pytest.approx(8.0)


def test_capture_negative_si_la_base_bouge_contre_nous():
    assert capture_base_bps(2.0, 10.0) == pytest.approx(-8.0)


def test_correction_sortie_retire_la_base_residuelle():
    # base pas convergee (reste +10) -> correction = -10 (on retire le premium fantome credite a l'entree)
    assert correction_sortie_bps(10.0) == pytest.approx(-10.0)
    # base convergee a 0 -> correction 0 (on garde le premium, il est capture)
    assert correction_sortie_bps(0.0) == pytest.approx(0.0)


def test_net_base_realise_est_le_vrai_pnl():
    # net = base_entree (credite par le cout) + correction(base_courant) == capture reelle
    base_entree, base_courant = 12.0, 3.0
    net = base_entree + correction_sortie_bps(base_courant)
    assert net == pytest.approx(capture_base_bps(base_entree, base_courant))   # 12 - 3 = 9


def test_base_convergee_premium_reel_capture():
    assert base_convergee(10.0, 1.0) is True       # reste 1 <= 30% de 10 -> converge
    assert base_convergee(10.0, 8.0) is False      # reste 8 > 30% -> pas encore


def test_base_negligeable_rien_a_verrouiller():
    assert base_convergee(1.0, 0.0) is False       # |entree| < min_bps -> pas un premium


def test_base_favorable_negative_converge_aussi():
    # une base -10 (perp moins cher) qui remonte vers 0 : premium capture aussi
    assert base_convergee(-10.0, -2.0) is True
