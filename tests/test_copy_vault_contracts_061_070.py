from __future__ import annotations

from hl_observer.copy_vault.copyability_erosion_monitor import erosion_receipt
from hl_observer.copy_vault.copyability_kill_switch import copyability_veto_receipt
from hl_observer.copy_vault.holding_time_compatibility import holding_time_receipt
from hl_observer.copy_vault.leader_execution_efficiency import execution_efficiency_receipt
from hl_observer.copy_vault.leader_price_quality_attribution import price_quality_receipt
from hl_observer.copy_vault.per_vault_replication_shortfall import shortfall_attribution_receipt
from hl_observer.copy_vault.source_execution_style_profile import execution_style_change_receipt
from hl_observer.copy_vault.source_maker_taker_classifier import maker_taker_receipt
from hl_observer.copy_vault.source_state_contradiction_penalty import contradiction_receipt
from hl_observer.research.wallet_copy_edge import temporal_placebo_receipt


def test_061_exceptional_leader_price_is_not_copyable() -> None:
    result = price_quality_receipt(prix_fill_leader=99.0, prix_marche_reference=100.0, sens="BUY")
    assert result["status"] == "PROVEN"
    assert result["copyable"] is False


def test_062_execution_efficiency_uses_causal_mid() -> None:
    result = execution_efficiency_receipt(fill_price=99.0, causal_mid=100.0, side="BUY")
    assert result["status"] == "PROVEN"
    assert result["efficiency_bps"] == 100.0
    assert result["causal_reference"] is True


def test_063_erosion_requires_recent_gap_increase() -> None:
    result = erosion_receipt([(1.0, 1.0), (1.0, 1.0), (2.0, 1.0), (2.0, 1.0)])
    assert result["status"] == "PROVEN"
    assert result["copyability_erosion"] is True


def test_064_copyability_veto_suspends_entries_but_not_management() -> None:
    result = copyability_veto_receipt([(5.0, 1.0), (5.0, 1.0), (5.0, 1.0)])
    assert result["status"] == "PROVEN"
    assert result["new_entries_suspended"] is True
    assert result["existing_position_management_allowed"] is True


def test_065_short_holding_is_incompatible_with_latency() -> None:
    result = holding_time_receipt(holding_seconds=1.0, copy_latency_seconds=2.0)
    assert result["status"] == "PROVEN"
    assert result["compatibility"] == "INCOMPATIBLE"


def test_066_missing_liquidity_signal_stays_unknown() -> None:
    assert maker_taker_receipt({"is_maker": True})["classification"] == "MAKER"
    assert maker_taker_receipt({})["status"] == "MORE_DATA"


def test_067_style_change_requires_revalidation() -> None:
    result = execution_style_change_receipt(
        {"taux_maker": 0.8, "taux_taker": 0.2, "part_partial": 0.1},
        {"taux_maker": 0.4, "taux_taker": 0.6, "part_partial": 0.1},
    )
    assert result["status"] == "PROVEN"
    assert result["style_changed"] is True
    assert result["revalidate_score"] is True


def test_068_shortfall_components_reconcile() -> None:
    result = shortfall_attribution_receipt(
        leader_return_bps=10.0,
        our_return_after_costs_bps=5.0,
        cost_bps=2.0,
        latency_bps=2.0,
        capacity_bps=1.0,
    )
    assert result["status"] == "PROVEN"
    assert result["reconciled"] is True


def test_069_contradictory_state_is_not_certifiable() -> None:
    result = contradiction_receipt(fill_action="REDUCE", position_before=1.0, position_after=2.0)
    assert result["status"] == "PROVEN"
    assert result["quarantaine"] is True
    assert result["certification_allowed"] is False


def test_070_observed_edge_must_beat_temporal_placebo() -> None:
    result = temporal_placebo_receipt(
        observed_net_bps=5.0, placebo_net_bps=1.0, observed_count=30, placebo_count=30
    )
    assert result["status"] == "PROVEN"
    assert result["beats_placebo"] is True
    assert result["decision"] == "CANDIDATE"
