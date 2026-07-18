"""C12/C13 — ne garder que les leaders qui PRÉDISENT (markout forward positif), jeter les contrariens."""
from __future__ import annotations

import pytest

from hl_observer.copy_wallet.leader_markout import (
    MIN_EVENEMENTS, markout_fill_bps, juger_leader, selectionner_leaders, copier_ce_leader,
)


def _fills(side, m0, m1, n):
    return [{"side": side, "mid_at_fill": m0, "mid_forward": m1} for _ in range(n)]


def test_markout_fill_signe_par_la_direction():
    assert markout_fill_bps("BUY", 100.0, 101.0) == pytest.approx(100.0)    # +1% = 100 bps, achat gagnant
    assert markout_fill_bps("SELL", 100.0, 101.0) == pytest.approx(-100.0)  # vente perdante
    assert markout_fill_bps("SELL", 100.0, 99.0) == pytest.approx(100.0)    # vente gagnante
    assert markout_fill_bps("BUY", 0.0, 1.0) is None                        # prix invalide


def test_leader_predicteur_est_garde():
    v = juger_leader("0xPRED", _fills("BUY", 100.0, 100.5, 30))    # +50 bps constants
    assert v.predit is True and v.markout_moyen_bps == pytest.approx(50.0)


def test_leader_contrarien_est_rejete():
    v = juger_leader("0xCONTRA", _fills("BUY", 100.0, 99.5, 30))   # -50 bps : contrarien
    assert v.predit is False and v.motif == "LEADER_CONTRARIEN_OU_NEUTRE"


def test_deny_by_default_trop_peu_d_events():
    v = juger_leader("0xNEW", _fills("BUY", 100.0, 101.0, MIN_EVENEMENTS - 1))
    assert v.predit is False and v.motif == "TROP_PEU_D_EVENEMENTS"


def test_selection_met_les_predicteurs_devant():
    par_leader = {
        "pred": _fills("BUY", 100.0, 100.8, 25),      # +80
        "contra": _fills("BUY", 100.0, 99.0, 25),     # -100
        "faible": _fills("BUY", 100.0, 100.2, 25),    # +20
    }
    ordre = [v.adresse for v in selectionner_leaders(par_leader)]
    assert ordre[0] == "pred" and ordre[1] == "faible" and ordre[-1] == "contra"
    assert [v.predit for v in selectionner_leaders(par_leader)][:2] == [True, True]


def test_c13_filtre_live():
    assert copier_ce_leader(_fills("SELL", 100.0, 99.0, 30)) is True     # vente gagnante -> copier
    assert copier_ce_leader(_fills("SELL", 100.0, 101.0, 30)) is False   # vente perdante -> ne pas copier
