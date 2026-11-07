"""Famille E #14 : mémoïsation de l'appariement d'entrée.

La partie invariante de `_segment_candidates` (features de profondeur causale +
notional du 1er fill, indépendants des params cherchés) est calculée une fois et
réutilisée via `prepared_cache`. Garantie QUALITÉ : la sortie (candidats + audit)
est STRICTEMENT identique avec ou sans cache, pour tout jeu de paramètres.
"""
from __future__ import annotations

from hl_observer.backtesting.copy_vault_v21_frozen import _segment_candidates


def _book(ts_ms: int, bid_px: float = 100.0, bid_sz: float = 5.0,
          ask_px: float = 102.0, ask_sz: float = 3.0) -> dict:
    return {
        "ts_ms": ts_ms,
        "causal_observation": True,
        "bid": bid_px,
        "ask": ask_px,
        "bids5": [[bid_px, bid_sz]],
        "asks5": [[ask_px, ask_sz]],
    }


def _meta(signal_ms: int, *, coin: str = "BTC", notional: float = 60.0, direction: int = 1) -> dict:
    return {
        "signal_ts_ms": signal_ms,
        "metaorder_id": f"m-{signal_ms}",
        "vault": f"v-{signal_ms}",
        "coin": coin,
        "direction": direction,
        "member_events": [{"action": "ADD", "taille_usd": notional}],
    }


_BOOKS = {"BTC": [_book(1_000)]}
_METAS = [_meta(1_100), _meta(1_200, notional=15.0), _meta(1_300)]
_PARAM_GRID = [(-1.0, 10.0), (0.0, 50.0), (0.5, 100.0), (-1.0, 10.0)]


def _run(cache, *, imbalance_min: float, notional_min: float):
    return _segment_candidates(
        _METAS, _BOOKS,
        start_ms=0, end_ms=None,
        minimum_leader_fill_notional_usd=notional_min,
        signed_depth_imbalance_minimum=imbalance_min,
        prepared_cache=cache,
    )


def test_shared_cache_matches_no_cache_for_every_param_set() -> None:
    cache: dict = {}
    for imbalance_min, notional_min in _PARAM_GRID:
        expected = _run(None, imbalance_min=imbalance_min, notional_min=notional_min)
        got = _run(cache, imbalance_min=imbalance_min, notional_min=notional_min)
        assert got == expected
    # La partie invariante n'a été calculée qu'une fois (une seule clé de bornes).
    assert len(cache) == 1


def test_cache_path_is_exercised_and_non_vacuous() -> None:
    # Paramètres laxistes -> les 3 metaorders passent (chemin non vide).
    candidates, audit = _run(None, imbalance_min=-1.0, notional_min=10.0)
    assert len(candidates) == 3
    assert audit["FIXED_POLICY_CANDIDATE"] == 3


def test_repeated_cached_calls_are_stable() -> None:
    cache: dict = {}
    first = _run(cache, imbalance_min=0.0, notional_min=50.0)
    second = _run(cache, imbalance_min=0.0, notional_min=50.0)
    third = _run(cache, imbalance_min=0.0, notional_min=50.0)
    assert first == second == third
