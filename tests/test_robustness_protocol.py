from __future__ import annotations

import pytest

from hl_observer.backtesting.robustness_protocol import (
    alternate_universe_partitions,
    apply_holdout_veto,
    freeze_train_selection,
    stress_cost_latency,
)


def test_holdout_is_veto_only_never_ranking_gradient():
    frozen = freeze_train_selection({"A": 5.0, "B": 4.0})
    assert frozen["winner"] == "A" and frozen["holdout_used_for_ranking"] is False
    assert apply_holdout_veto(frozen, oos_passed=True, forward_passed=True)["verdict"] == "CONFIRMED"
    veto = apply_holdout_veto(frozen, oos_passed=False, forward_passed=True)
    assert veto["winner"] == "A" and veto["verdict"] == "VETO" and veto["retune_allowed"] is False
    with pytest.raises(ValueError):
        apply_holdout_veto({**frozen, "holdout_used_for_ranking": True}, oos_passed=True, forward_passed=True)


def test_cost_latency_stress_is_deterministic_and_fail_closed():
    rows = stress_cost_latency(fees_bps=4, slippage_bps=3, latency_bps=2)
    assert rows == stress_cost_latency(fees_bps=4, slippage_bps=3, latency_bps=2)
    assert rows[-1]["total_cost_bps"] == pytest.approx(18.0)
    with pytest.raises(ValueError):
        stress_cost_latency(fees_bps=-1, slippage_bps=0, latency_bps=0)


def test_alternate_universes_are_order_independent_and_disjoint():
    a = alternate_universe_partitions(["BTC", "ETH", "SOL", "HYPE", "DOGE", "XRP"], partitions=3)
    b = alternate_universe_partitions(["XRP", "DOGE", "HYPE", "SOL", "ETH", "BTC"], partitions=3)
    assert a == b
    flattened = [item for bucket in a for item in bucket]
    assert len(flattened) == len(set(flattened)) == 6
