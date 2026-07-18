"""Portefeuille carry — risk-parity (plus de capital aux moins risqués), n'alloue qu'aux net>0,
rotation avec hysteresis. Beaucoup d'ouvertures propres, barre jamais baissée."""
from __future__ import annotations

from hl_observer.funding.carry_portfolio import allouer_portefeuille, poids_risk_parity, rotation_justifiee


def test_risk_parity_favorise_le_moins_volatil():
    p = poids_risk_parity([{"coin": "A", "vol": 0.1}, {"coin": "B", "vol": 0.4}])
    assert p["A"] > p["B"]                              # A moins volatil -> plus de poids
    assert abs(sum(p.values()) - 1.0) < 1e-6           # normalisé


def test_allocation_seulement_net_positif_et_cappee():
    carries = [{"coin": "A", "gain_net_bps": 30, "vol": 0.2},
               {"coin": "B", "gain_net_bps": 10, "vol": 0.2},
               {"coin": "C", "gain_net_bps": -5, "vol": 0.2}]   # C négatif -> exclu
    alloc = allouer_portefeuille(carries, 1000.0, max_slots=5)
    assert "C" not in alloc and set(alloc) == {"A", "B"}
    assert abs(sum(alloc.values()) - 1000.0) < 1.0     # tout le capital réparti
    alloc2 = allouer_portefeuille(carries, 1000.0, max_slots=1)
    assert set(alloc2) == {"A"}                         # cappé au meilleur net


def test_rotation_hysteresis():
    assert rotation_justifiee(10.0, 40.0) is True       # +30 > coût rotation 22
    assert rotation_justifiee(10.0, 25.0) is False      # +15 < 22 -> on ne churne pas
