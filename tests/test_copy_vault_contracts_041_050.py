from __future__ import annotations

from hl_observer.copy_vault.ambiguous_action_deny import decision_with_pre_state
from hl_observer.copy_vault.capture_leader_margin_mode import margin_sizing_receipt
from hl_observer.copy_vault.coherent_snapshot_open import snapshot_version_receipt
from hl_observer.copy_vault.collateral_change_rebaseline import rebaseline_receipt
from hl_observer.copy_vault.deposit_withdrawal_detector import transfer_exclusion_receipt
from hl_observer.copy_vault.dual_source_verification import independent_state_receipt
from hl_observer.copy_vault.flip_as_two_operations import flip_cost_receipt
from hl_observer.copy_vault.scale_in_reconstruction import scale_in_receipt
from hl_observer.copy_vault.scale_out_reconstruction import scale_out_receipt
from hl_observer.copy_vault.startup_position_bootstrap import bootstrap_entry_receipt
from hl_observer.wallets.position_rebuilder import position_reconciliation_receipt


def test_bootstrap_mid_position_does_not_fabricate_open() -> None:
    result = bootstrap_entry_receipt(bootstrap_ready=False, live_action="OPEN")
    assert result["status"] == "PROVEN"
    assert result["new_entry"] is False


def test_snapshot_versions_must_match_for_open() -> None:
    assert snapshot_version_receipt(version_equity="v1", version_positions="v2")["open_allowed"] is False
    assert snapshot_version_receipt(version_equity="v1", version_positions="v1")["open_allowed"] is True


def test_independent_sources_conflict_blocks_open() -> None:
    result = independent_state_receipt(["a"], ["b"])
    assert result["status"] == "PROVEN"
    assert result["open_allowed"] is False


def test_unknown_margin_mode_blocks_sizing() -> None:
    assert margin_sizing_receipt("unknown")["sizing_allowed"] is False
    assert margin_sizing_receipt("isolated")["sizing_allowed"] is True


def test_external_transfer_is_not_pnl_or_fill() -> None:
    result = transfer_exclusion_receipt(equity_avant=100.0, equity_apres=150.0, pnl_trading=1.0)
    assert result["status"] == "PROVEN"
    assert result["counts_as_pnl"] is False
    assert result["creates_fill"] is False


def test_collateral_change_requires_new_reference() -> None:
    result = rebaseline_receipt(collateral_changed=True, equity_after=200.0)
    assert result["status"] == "PROVEN"
    assert result["sizing_allowed"] is True
    assert result["historical_returns_unchanged"] is True


def test_rebuilt_position_divergence_is_rejected() -> None:
    result = position_reconciliation_receipt(rebuilt_size=2.0, snapshot_size=3.0)
    assert result["status"] == "PROVEN"
    assert result["open_allowed"] is False


def test_flip_costs_have_two_separate_legs() -> None:
    result = flip_cost_receipt(position_avant=2.0, position_cible=-1.0, close_cost=0.2, open_cost=0.3)
    assert result["status"] == "PROVEN"
    assert result["two_legs"] is True
    assert result["total_cost"] == 0.5


def test_scale_in_uses_observed_legs() -> None:
    result = scale_in_receipt([
        {"action": "OPEN", "qty": 1.0, "prix": 10.0, "sens": "LONG"},
        {"action": "ADD", "qty": 1.0, "prix": 12.0, "sens": "LONG"},
    ])
    assert result["status"] == "PROVEN"
    assert result["detail"]["qte_cumulee"] == 2.0


def test_scale_out_reports_only_realized_quantity() -> None:
    result = scale_out_receipt([
        {"action": "REDUCE", "qty": 0.5, "prix": 11.0},
        {"action": "CLOSE", "qty": 0.5, "prix": 9.0},
    ])
    assert result["status"] == "PROVEN"
    assert result["realized_quantity"] == 1.0
