"""L1 — moteur maker/taker + L3 anti-gaming + L5 coupe de fraîcheur."""
from __future__ import annotations

import random

from hl_observer.execution.maker_taker import (
    POSTER_MAKER, PRENDRE_TAKER, NE_PAS_TRADER, decision_maker_taker)
from hl_observer.execution.anti_gaming import taille_randomisee, delai_randomise_ms
from hl_observer.execution.freshness_cut import frais_pour_envoi


def test_maker_si_pas_urgent_et_ev_positive():
    d = decision_maker_taker(edge_bps=60.0, prob_fill=0.8, rebate_bps=5.0, selection_adverse_bps=1.0,
                             cout_taker_bps=10.0, urgent=False, min_edge_bps=30.0)
    assert d == POSTER_MAKER


def test_taker_si_urgent_et_edge_survit():
    d = decision_maker_taker(edge_bps=60.0, prob_fill=0.8, rebate_bps=5.0, selection_adverse_bps=1.0,
                             cout_taker_bps=10.0, urgent=True, min_edge_bps=30.0)
    assert d == PRENDRE_TAKER                       # 60-10=50 >= 30


def test_ne_pas_trader_si_edge_mort_apres_taker():
    d = decision_maker_taker(edge_bps=35.0, prob_fill=0.5, rebate_bps=1.0, selection_adverse_bps=9.0,
                             cout_taker_bps=10.0, urgent=True, min_edge_bps=30.0)
    assert d == NE_PAS_TRADER                       # 35-10=25 < 30 ; ev maker negatif


def test_l3_taille_bornee_et_positive():
    rng = random.Random(42)
    for _ in range(50):
        t = taille_randomisee(100.0, jitter_frac=0.15, rng=rng)
        assert 85.0 <= t <= 115.0
    assert delai_randomise_ms(1000.0, jitter_ms=500.0, rng=rng) >= 1000.0   # jamais plus rapide


def test_l5_fraicheur():
    assert frais_pour_envoi(60.0, max_age_s=120.0) is True
    assert frais_pour_envoi(200.0, max_age_s=120.0) is False    # trop vieux
    assert frais_pour_envoi(None) is False                       # age inconnu -> perime
