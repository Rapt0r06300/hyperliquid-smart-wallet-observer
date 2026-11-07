"""Famille B #5/#6 : proposition ordonnee par plausibilite (grossier->fin).

Le meme espace de recherche, reordonne centre-dehors : les configs moderees /
plausibles sortent aux petits index Halton. Deterministe et reproductible ;
n'altere ni l'espace ni la rigueur (TRAIN-only, Bonferroni accumule inchange).
"""
from __future__ import annotations

from hl_observer.backtesting.copy_vault_local_lab import (
    _PARAMETER_DOMAINS,
    _PLAUSIBILITY_DOMAINS,
    _campaign_search_config,
    _candidate_parameters,
    _center_out_order,
    _search_space_size,
)


def test_center_out_order_is_median_first_and_preserves_the_set() -> None:
    assert _center_out_order((1, 2, 3, 4, 5)) == (3, 4, 2, 5, 1)
    assert _center_out_order((10,)) == (10,)
    assert _center_out_order(()) == ()
    for _name, domain in _PARAMETER_DOMAINS:
        assert set(_center_out_order(domain)) == set(domain)
        assert len(_center_out_order(domain)) == len(domain)


def test_plausibility_domains_same_values_as_canonical() -> None:
    assert [name for name, _ in _PLAUSIBILITY_DOMAINS] == [name for name, _ in _PARAMETER_DOMAINS]
    for (_n1, ordered), (_n2, canonical) in zip(_PLAUSIBILITY_DOMAINS, _PARAMETER_DOMAINS, strict=True):
        assert set(ordered) == set(canonical)


def test_search_space_size_is_unchanged_by_reordering() -> None:
    # La taille de l'espace ne depend que des valeurs, pas de l'ordre.
    assert _search_space_size() > 0
    import math
    core = dict(_PARAMETER_DOMAINS)["core_notional_usd"]
    probe = dict(_PARAMETER_DOMAINS)["probe_notional_usd"]
    from hl_observer.backtesting.copy_vault_local_lab import PAPER_CAPITAL_USD
    pairs = sum(1 for a in core for b in probe if a + b <= PAPER_CAPITAL_USD)
    rest = math.prod(len(d) for _n, d in _PARAMETER_DOMAINS[2:])
    assert _search_space_size() == pairs * rest


def test_early_candidate_uses_central_plausible_values() -> None:
    first = _candidate_parameters(1)
    assert first is not None
    # Petits domaines : l'index 1 tombe sur la valeur centrale (plausible).
    assert first["vault_daily_limit"] == 3   # centre de (2, 3, 4)
    assert first["coin_daily_limit"] == 3    # centre de (2, 3, 4)
    assert first["max_open_positions"] == 2  # centre de (1, 2, 3)
    # Imbalance proche de la symetrie (|x| petit), pas un extreme.
    assert abs(first["signed_depth_imbalance_minimum"]) <= 0.1


def test_config_records_the_ordered_proposal_contract() -> None:
    config, digest = _campaign_search_config({"train_start_ms": 1, "train_end_ms": 2})
    assert config["proposal_method"] == "HALTON_PLAUSIBILITY_ORDERED_V2"
    assert set(config["parameter_proposal_order"]) == {n for n, _ in _PARAMETER_DOMAINS}
    assert len(digest) == 64
