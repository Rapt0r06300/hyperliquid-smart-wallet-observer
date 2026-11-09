"""Variante overshoot : filtre causal + wiring de l'explorateur (additif, sûr)."""
from __future__ import annotations

from hl_observer.backtesting.copy_vault_overshoot_train import (
    SEUILS_OVERSHOOT_BPS,
    explore_overshoot_filtered_train,
    filtrer_continuations,
)
from hl_observer.backtesting.overshoot_signal import build_overshoot_index


def test_filtre_bloque_les_coins_en_debordement():
    # BTC en gros overshoot (+300 bps) à t=2000 ; ETH calme.
    asset_ctx = [
        {"coin": "BTC", "ts_ms": 1000, "mark": 103.0, "oracle": 100.0},  # +300 bps
        {"coin": "ETH", "ts_ms": 1000, "mark": 50.0, "oracle": 50.0},    # 0 bps
    ]
    index = build_overshoot_index(asset_ctx)
    continuations = [
        {"coin": "BTC", "signal_ts_ms": 2000, "metaorder_id": "a"},
        {"coin": "ETH", "signal_ts_ms": 2000, "metaorder_id": "b"},
    ]
    # seuil 100 bps : BTC (300) bloqué, ETH gardé.
    gardees = filtrer_continuations(continuations, index, 100.0)
    coins = {c["coin"] for c in gardees}
    assert coins == {"ETH"}, coins
    # seuil None : tout gardé.
    assert len(filtrer_continuations(continuations, index, None)) == 2
    # seuil très haut (500) : rien bloqué.
    assert len(filtrer_continuations(continuations, index, 500.0)) == 2


def test_filtre_causal_pas_de_futur():
    # overshoot n'apparaît qu'à t=3000 ; une entrée à t=2000 ne doit PAS être bloquée.
    asset_ctx = [
        {"coin": "BTC", "ts_ms": 1000, "mark": 100.0, "oracle": 100.0},  # 0
        {"coin": "BTC", "ts_ms": 3000, "mark": 110.0, "oracle": 100.0},  # +1000 bps (futur)
    ]
    index = build_overshoot_index(asset_ctx)
    cont = [{"coin": "BTC", "signal_ts_ms": 2000, "metaorder_id": "a"}]
    # à t=2000 l'overshoot causal est 0 -> gardé malgré le pic futur.
    assert len(filtrer_continuations(cont, index, 100.0)) == 1


def test_explore_smoke_structure_et_trial_count():
    # Données minimales : pas de trades éligibles (normal), mais l'explorateur tourne,
    # produit la grille complète et un trial_count cohérent, sans crash.
    res = explore_overshoot_filtered_train([], {}, [])
    assert res["mechanism"] == "copy_vault_overshoot_filtered_v1"
    # trial_count = required(4) × horizons × seuils(4)
    assert res["trial_count"] == len(res["variants"]) > 0
    assert res["eligible_count"] == 0  # aucune donnée -> rien d'éligible
    # chaque variante porte bien la dimension overshoot
    assert all("overshoot_seuil_bps" in v for v in res["variants"])
    assert {v["overshoot_seuil_bps"] for v in res["variants"]} == set(SEUILS_OVERSHOOT_BPS)
