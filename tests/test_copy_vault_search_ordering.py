"""Ordre de proposition plausible pour la recherche Copy-Vault.

L'ordre centre-dehors place les valeurs moderees plus tot dans la sequence Halton.
Les domaines restent ceux du contrat courant, notamment le levier fixe a 1x.
La selection reste TRAIN-only et chaque tentative contribue au Bonferroni.
"""
from __future__ import annotations

from hl_observer.backtesting.copy_vault_local_lab import (
    _PARAMETER_DOMAINS,
    _PLAUSIBILITY_DOMAINS,
    BASELINE_COMPARISON_BASIS,
    _campaign_search_config,
    _candidate_parameters,
    _center_out_order,
    _search_space_size,
)
from hl_observer.backtesting.copy_vault_protocol import PAPER_LEVERAGE


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


def test_leverage_is_a_fixed_paper_contract_not_a_search_axis() -> None:
    assert dict(_PARAMETER_DOMAINS)["paper_leverage"] == (PAPER_LEVERAGE,)
    assert PAPER_LEVERAGE == 1.0
    for sequence_index in range(1, 33):
        candidate = _candidate_parameters(sequence_index)
        if candidate is not None:
            assert candidate["paper_leverage"] == 1.0
    assert BASELINE_COMPARISON_BASIS == "CURRENT_COPY_VAULT_SETTINGS_NORMALIZED_TO_100_USD"


def test_config_records_the_ordered_proposal_contract() -> None:
    config, digest = _campaign_search_config({"train_start_ms": 1, "train_end_ms": 2})
    assert config["proposal_method"] == "HALTON_PLAUSIBILITY_ORDERED_V2"
    assert set(config["parameter_proposal_order"]) == {n for n, _ in _PARAMETER_DOMAINS}
    assert config["parameter_domains"]["paper_leverage"] == [1.0]
    assert len(digest) == 64
