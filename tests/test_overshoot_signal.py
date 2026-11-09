"""Signal overshoot : exactitude + CAUSALITÉ stricte (jamais de look-ahead)."""
from __future__ import annotations

from hl_observer.backtesting.overshoot_signal import (
    build_overshoot_index,
    copie_bloquee,
    overshoot_bps_at,
)


def _rows():
    return [
        {"coin": "BTC", "ts_ms": 1000, "mark": 100.0, "oracle": 100.0},   # overshoot 0
        {"coin": "BTC", "ts_ms": 2000, "mark": 101.0, "oracle": 100.0},   # +100 bps
        {"coin": "BTC", "ts_ms": 3000, "mark": 98.0, "oracle": 100.0},    # -200 bps
        {"coin": "eth", "ts_ms": 1500, "mark": 50.5, "oracle": 50.0},     # +100 bps (casse)
        {"coin": "X", "ts_ms": 100, "mark": 1.0, "oracle": 0.0},          # oracle<=0 -> ignoré
        {"coin": "Y", "ts_ms": 200, "mark": "n/a", "oracle": 1.0},        # mark invalide -> ignoré
    ]


def test_calcul_overshoot_bps():
    idx = build_overshoot_index(_rows())
    assert overshoot_bps_at(idx, "BTC", 2000) == 100.0
    assert overshoot_bps_at(idx, "BTC", 3000) == -200.0
    # insensible à la casse du coin
    assert abs(overshoot_bps_at(idx, "ETH", 1500) - 100.0) < 1e-9


def test_causalite_stricte_pas_de_futur():
    idx = build_overshoot_index(_rows())
    # avant le 1er snapshot -> aucun signal causal
    assert overshoot_bps_at(idx, "BTC", 999) is None
    # entre 1000 et 2000 -> on prend 1000 (le passé), JAMAIS 2000 (futur)
    assert overshoot_bps_at(idx, "BTC", 1999) == 0.0
    # pile sur un snapshot -> ce snapshot
    assert overshoot_bps_at(idx, "BTC", 2000) == 100.0
    # après le dernier -> le dernier connu
    assert overshoot_bps_at(idx, "BTC", 99999) == -200.0


def test_lignes_invalides_ignorees():
    idx = build_overshoot_index(_rows())
    assert "X" not in idx  # oracle<=0
    assert "Y" not in idx  # mark invalide


def test_copie_bloquee_seuil():
    idx = build_overshoot_index(_rows())
    # à 3000, overshoot=-200bps ; seuil 150 -> bloqué ; seuil 250 -> pas bloqué
    assert copie_bloquee(idx, "BTC", 3000, seuil_bps=150) is True
    assert copie_bloquee(idx, "BTC", 3000, seuil_bps=250) is False
    # pas de signal causal (avant 1er snapshot ou coin inconnu) -> jamais bloqué (fail-open)
    assert copie_bloquee(idx, "BTC", 500, seuil_bps=1) is False
    assert copie_bloquee(idx, "ZZZ", 3000, seuil_bps=1) is False


def test_robuste_entrees_vides():
    assert build_overshoot_index(None) == {}
    assert build_overshoot_index([]) == {}
    assert overshoot_bps_at({}, "BTC", 1000) is None
    assert copie_bloquee({}, "BTC", 1000, seuil_bps=10) is False
