"""A7 — rotation avec hysteresis : ne remplacer un carry que si le surplus couvre le cout de rotation."""
from __future__ import annotations

from hl_observer.funding.carry_rotation import (
    COUT_ROTATION_BPS, rotation_justifiee, selection_avec_rotation,
)


def test_rotation_refusee_pour_gain_marginal():
    # surplus quotidien 5 bps < cout 22 -> on ne churne pas
    assert rotation_justifiee(30.0, 35.0) is False


def test_rotation_acceptee_si_surplus_couvre_le_cout():
    # surplus 30 bps/24h > 22 -> justifie
    assert rotation_justifiee(30.0, 60.0) is True


def test_slots_libres_ouvrent_les_meilleurs():
    a_ouvrir, a_fermer = selection_avec_rotation(
        {}, {"A": 50.0, "B": 80.0, "C": 10.0}, max_slots=2)
    assert set(a_ouvrir) == {"B", "A"}          # 2 slots libres -> les 2 meilleurs
    assert a_fermer == []


def test_slots_pleins_pas_de_rotation_marginale():
    # ouverts A(50) B(48) pleins ; challenger C(55) ne bat le pire (48) que de 7 < 22 -> pas de rotation
    a_ouvrir, a_fermer = selection_avec_rotation(
        {"A": 50.0, "B": 48.0}, {"C": 55.0}, max_slots=2)
    assert a_ouvrir == [] and a_fermer == []


def test_slots_pleins_rotation_si_challenger_bien_meilleur():
    # challenger C(90) bat le pire (48) de 42 > 22 -> rotation justifiee
    a_ouvrir, a_fermer = selection_avec_rotation(
        {"A": 50.0, "B": 48.0}, {"C": 90.0}, max_slots=2)
    assert a_ouvrir == ["C"] and a_fermer == ["B"]


def test_cout_rotation_est_un_round_trip():
    assert COUT_ROTATION_BPS >= 22.0            # 2 sorties + 2 entrees maker (2 jambes)
