"""#10 — signal de qualité leader causal (closedPnl cumulé) : prouve causalité + fail-open."""
from __future__ import annotations

from hl_observer.backtesting.leader_quality_signal import (
    SEUIL_LEADER_OFF_USD,
    build_leader_quality_index,
    copie_leader_faible,
    leader_prior_pnl_at,
)

# Leader A : +10 à t=1000, -30 à t=2000 (cumul: +10 puis -20). Leader B : +50 à t=1500.
_FILLS = [
    {"vault": "A", "ts_ms": 1000, "closed_pnl": 10.0},
    {"vault": "A", "ts_ms": 2000, "closed_pnl": -30.0},
    {"vault": "B", "ts_ms": 1500, "closed_pnl": 50.0},
    {"vault": "A", "ts_ms": 500, "closed_pnl": 0.0},   # ordre d'entrée mélangé
]


def test_cumul_causal_par_vault():
    idx = build_leader_quality_index(_FILLS)
    # Un fill au même milliseconde n'est pas prouvé antérieur au signal.
    assert leader_prior_pnl_at(idx, "A", 1000) == 0.0
    # A à t=1999 : toujours +10 (le -30 est à t=2000, pas encore)
    assert leader_prior_pnl_at(idx, "A", 1999) == 10.0
    # Le fill négatif de t=2000 n'est visible qu'après cette milliseconde.
    assert leader_prior_pnl_at(idx, "A", 2000) == 10.0
    assert leader_prior_pnl_at(idx, "A", 2001) == -20.0
    assert leader_prior_pnl_at(idx, "B", 1500) is None
    assert leader_prior_pnl_at(idx, "B", 1501) == 50.0


def test_pas_de_look_ahead_avant_premier_fill():
    idx = build_leader_quality_index(_FILLS)
    # avant le 1er fill de A (t=500) -> None (aucune info causale)
    assert leader_prior_pnl_at(idx, "A", 499) is None
    # leader inconnu -> None
    assert leader_prior_pnl_at(idx, "ZZZ", 9999) is None
    # A timestamp must be an exact positive integer; never truncate or coerce it.
    for invalid_timestamp in (True, 1000.0, "1000", 0, -1, None):
        assert leader_prior_pnl_at(idx, "A", invalid_timestamp) is None


def test_filtre_bloque_leader_faible_et_fail_open():
    idx = build_leader_quality_index(_FILLS)
    # Le -30 reçu à t=2000 ne peut pas bloquer un signal de t=2000.
    assert copie_leader_faible(idx, "A", 2000, seuil_usd=0.0) is False
    assert copie_leader_faible(idx, "A", 2001, seuil_usd=0.0) is True
    # À t=1000, seul le zéro de t=500 est disponible.
    assert copie_leader_faible(idx, "A", 1000, seuil_usd=0.0) is False
    # Le premier résultat de B n'est disponible qu'après t=1500.
    assert copie_leader_faible(idx, "B", 1500, seuil_usd=100.0) is False
    assert copie_leader_faible(idx, "B", 1501, seuil_usd=100.0) is True
    # fail-open : pas d'historique causal -> jamais bloqué
    assert copie_leader_faible(idx, "A", 499, seuil_usd=0.0) is False
    assert copie_leader_faible(idx, "INCONNU", 1500, seuil_usd=0.0) is False


def test_seuil_off_ne_bloque_jamais():
    idx = build_leader_quality_index(_FILLS)
    # même le pire leader n'est jamais < OFF
    assert copie_leader_faible(idx, "A", 2000, seuil_usd=SEUIL_LEADER_OFF_USD) is False


def test_fail_soft_donnees_invalides():
    idx = build_leader_quality_index([
        {"vault": "", "ts_ms": 1, "closed_pnl": 1.0},        # vault vide
        {"vault": "X", "ts_ms": None, "closed_pnl": 1.0},    # ts invalide
        {"vault": "X", "ts_ms": 10, "closed_pnl": "NaNish"}, # pnl non numérique
        {"vault": "X", "ts_ms": 30, "closed_pnl": True},     # bool n'est pas un PnL
        {"vault": "X", "ts_ms": 20, "closed_pnl": 5.0},      # valide
    ])
    assert leader_prior_pnl_at(idx, "X", 31) == 5.0
    assert build_leader_quality_index(None) == {}
