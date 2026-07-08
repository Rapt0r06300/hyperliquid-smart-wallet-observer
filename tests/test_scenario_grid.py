"""Generateur de scenarios replay etendu : taille (dizaines de milliers), dedup, determinisme."""

from __future__ import annotations

from hl_observer.backtesting.scenario_grid import (
    archetype_scenarios, generate, grid_scenarios, sampled_scenarios,
)


def test_grid_size_exact():
    # SL(5) x TP(6) x trailing(4) x horizon(5) x min_edge(5) = 3000
    assert len(grid_scenarios()) == 5 * 6 * 4 * 5 * 5


def test_generate_reaches_tens_of_thousands_deduped():
    s = generate(max_scenarios=20000, seed=1)
    assert len(s) >= 15000
    assert len({sc.key() for sc in s}) == len(s)  # aucun doublon


def test_generate_deterministic_for_seed():
    assert [x.key() for x in generate(8000, seed=7)] == [x.key() for x in generate(8000, seed=7)]


def test_cap_is_respected():
    assert len(generate(max_scenarios=200)) == 200


def test_trailing_off_zeros_secondary_params():
    for s in sampled_scenarios(60, seed=5):
        if s.trailing_stop_bps == 0.0:
            assert s.trailing_activation_bps == 0.0
            assert s.breakeven_bps == 0.0
