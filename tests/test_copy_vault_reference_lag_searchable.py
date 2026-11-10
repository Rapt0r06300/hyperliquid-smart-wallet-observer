"""#5 — fenêtre causale (lag L2) CHERCHABLE : prouve le chemin NON-défaut.

Les gardiens v21 n'exercent que le lag par défaut (30_000). Ici on prouve que :
1. un lag plus large admet un fill que le lag par défaut JETTE (sans fuite look-ahead) ;
2. le ``prepared_cache`` sépare bien les lags (pas de collision de clé).
"""
from __future__ import annotations

import hl_observer.backtesting.copy_vault_v21_frozen as V21

# Carnet causal valide à t=1000. Signal 45 s plus tard (t=46_000).
_BOOKS = {
    "BTC": [
        {"ts_ms": 1_000, "causal_observation": True,
         "bids5": [[100.0, 2.0]], "asks5": [[101.0, 1.0]]},
    ]
}
_META = [{
    "signal_ts_ms": 46_000,  # 45 s après le dernier carnet
    "direction": 1,
    "coin": "BTC",
    "member_events": [{"action": "ADD", "taille_usd": 150.0}],
}]


def _candidats(lag, cache=None):
    return V21._segment_candidates(
        _META, _BOOKS,
        start_ms=900, end_ms=100_000,
        minimum_leader_fill_notional_usd=100.0,
        signed_depth_imbalance_minimum=-1.0,
        max_reference_lag_ms=lag,
        prepared_cache=cache,
    )


def test_lag_large_admet_un_fill_que_le_defaut_jette():
    # lag 30 s (défaut v21) : 45 s > 30 s -> fill JETÉ.
    c30, a30 = _candidats(30_000)
    assert len(c30) == 0
    assert a30.get("REFERENCE_DEPTH_FEATURE_UNMEASURABLE", 0) == 1
    # lag 60 s : 45 s <= 60 s -> fill ADMIS (toujours causal : carnet <= signal).
    c60, a60 = _candidats(60_000)
    assert len(c60) == 1
    assert a60.get("FIXED_POLICY_CANDIDATE", 0) == 1


def test_prepared_cache_separe_les_lags():
    # Un même cache partagé entre deux lags ne doit PAS mélanger les résultats.
    cache: dict = {}
    c30, _ = _candidats(30_000, cache)
    c60, _ = _candidats(60_000, cache)
    assert len(c30) == 0 and len(c60) == 1
    # deux entrées distinctes (clé inclut le lag), pas une collision.
    assert len([k for k in cache if k[2] == 30_000]) == 1
    assert len([k for k in cache if k[2] == 60_000]) == 1


def test_reste_causal_pas_de_carnet_futur():
    # Un carnet uniquement APRÈS le signal reste inutilisable, même avec un grand lag.
    books_futur = {"BTC": [
        {"ts_ms": 90_000, "causal_observation": True,
         "bids5": [[100.0, 2.0]], "asks5": [[101.0, 1.0]]},
    ]}
    c, a = V21._segment_candidates(
        _META, books_futur, start_ms=900, end_ms=100_000,
        minimum_leader_fill_notional_usd=100.0,
        signed_depth_imbalance_minimum=-1.0,
        max_reference_lag_ms=300_000,
    )
    assert len(c) == 0  # jamais de carnet futur, quel que soit le lag
