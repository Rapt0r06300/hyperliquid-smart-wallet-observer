"""κ — l'intensité de fill. On vérifie qu'on MESURE, et surtout qu'on REFUSE quand il le faut."""
from __future__ import annotations

import math

from hl_observer.market.fill_intensity import estimer


def _synthetique(A: float, kappa: float, distances):
    return [(d, A * math.exp(-kappa * d)) for d in distances]


def test_retrouve_A_et_kappa_connus() -> None:
    obs = _synthetique(0.8, 0.10, [0.0, 5.0, 10.0, 20.0, 40.0])
    r = estimer(obs)
    assert r is not None
    assert abs(r.A - 0.8) < 1e-3
    assert abs(r.kappa - 0.10) < 1e-3
    assert r.r2 > 0.99
    # la proba décroît avec la distance et reste dans [0, 1]
    assert r.proba(0.0) > r.proba(10.0) > r.proba(40.0) >= 0.0
    assert r.proba(0.0) <= 1.0


def test_refuse_si_pas_assez_de_points() -> None:
    # 2 distances distinctes seulement → on ne prétend rien
    assert estimer([(0.0, 0.9), (10.0, 0.4)]) is None


def test_refuse_si_le_fill_AUGMENTE_avec_la_distance() -> None:
    # κ ≤ 0 = modèle absurde (plus loin = plus rempli) → REFUS
    obs = [(0.0, 0.2), (10.0, 0.4), (20.0, 0.8)]
    assert estimer(obs) is None


def test_refuse_si_fill_au_mid_depasse_100pct() -> None:
    # A > 1 : un modèle qui remplit à >100 % au mid est FAUX → REFUS (il ressusciterait un MM mort)
    obs = _synthetique(1.8, 0.10, [0.0, 5.0, 10.0, 20.0])
    assert estimer(obs) is None


def test_ignore_les_taux_nuls_ou_negatifs() -> None:
    obs = _synthetique(0.7, 0.08, [0.0, 5.0, 10.0, 20.0]) + [(30.0, 0.0), (35.0, -1.0)]
    r = estimer(obs)
    assert r is not None and 0.0 < r.A <= 1.0 and r.kappa > 0.0
