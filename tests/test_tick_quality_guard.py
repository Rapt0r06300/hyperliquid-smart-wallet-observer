"""G4 — qualité des ticks : garde anti-stale + skip du 1er tick post-(re)connexion."""
from __future__ import annotations

from hl_observer.realtime.tick_quality_guard import tick_est_stale, GardeConnexion


def test_stale_si_delta_trop_grand():
    assert tick_est_stale(130.0, 100.0, delta_max_frac=0.15) is True    # +30% -> stale
    assert tick_est_stale(101.0, 100.0, delta_max_frac=0.15) is False   # +1% -> ok


def test_prix_invalide_est_stale():
    assert tick_est_stale(0.0, 100.0) is True
    assert tick_est_stale("x", 100.0) is True


def test_premier_tick_est_skippe():
    g = GardeConnexion()
    assert g.accepter("c1", 100.0, 100.0) is False     # 1er tick = snapshot cache -> skip
    assert g.accepter("c1", 100.5, 100.0) is True      # 2e tick sain -> accepte


def test_stale_rejete_apres_le_premier():
    g = GardeConnexion(delta_max_frac=0.1)
    g.accepter("c1", 100.0, 100.0)                      # skip 1er
    assert g.accepter("c1", 130.0, 100.0) is False     # 2e mais stale -> rejete


def test_reconnexion_reskippe():
    g = GardeConnexion()
    g.accepter("c1", 100.0, 100.0)                      # skip 1er
    g.accepter("c1", 100.1, 100.0)                      # accepte
    g.reconnexion("c1")
    assert g.accepter("c1", 100.1, 100.0) is False     # apres reco -> skip a nouveau


def test_sans_reference_on_ne_juge_pas_stale():
    g = GardeConnexion()
    g.accepter("c1", 100.0, None)                       # skip 1er
    assert g.accepter("c1", 999.0, None) is True        # pas de reference -> accepte (pas de faux rejet)
