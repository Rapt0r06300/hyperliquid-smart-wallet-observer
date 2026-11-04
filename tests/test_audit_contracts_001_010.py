from hl_observer.audit.copy_vault_audit_controls import (
    canonical_spec_freeze_receipt,
    champion_nonmeasurable_receipt,
    certification_gate_receipt,
    docs_scope_receipt,
    epoch_scoreboard_receipt,
    historical_tasklist_receipt,
    objective_state_head_receipt,
    partial_sample_exclusion_receipt,
    rejected_inventory_exclusion_receipt,
    runbook_dynamic_target_receipt,
)


def test_aud001_docs_are_copy_vault_only() -> None:
    row = {"active_family": "Copy-Vault", "active_family_count": 1, "fixed_multi_family_target": False}
    assert docs_scope_receipt([row])["status"] == "PROVEN"
    row["active_family_count"] = 2
    assert docs_scope_receipt([row])["status"] == "REJECTED"


def test_aud002_runbook_has_dynamic_target_and_freeze() -> None:
    row = {"fixed_target": False, "freeze_protocol": True, "continuous_discovery": True}
    assert runbook_dynamic_target_receipt([row])["status"] == "PROVEN"
    row["fixed_target"] = True
    assert runbook_dynamic_target_receipt([row])["status"] == "REJECTED"


def test_aud003_canonical_spec_is_frozen_in_place() -> None:
    row = {"canonical_spec": True, "parallel_spec": False, "target_fixed": False, "freeze_contract": True}
    assert canonical_spec_freeze_receipt([row])["status"] == "PROVEN"
    row["parallel_spec"] = True
    assert canonical_spec_freeze_receipt([row])["status"] == "REJECTED"


def test_aud004_objective_and_state_share_head() -> None:
    row = {"objective_sha": "sha", "state_sha": "sha", "stale": False}
    assert objective_state_head_receipt([row])["status"] == "PROVEN"
    row["state_sha"] = "other"
    assert objective_state_head_receipt([row])["status"] == "UNMEASURABLE"


def test_aud005_certification_gate_is_target_independent() -> None:
    row = {"fixed_target": False, "proof_gate": True, "small_gain_allowed": True}
    assert certification_gate_receipt([row])["status"] == "PROVEN"
    row["proof_gate"] = False
    assert certification_gate_receipt([row])["status"] == "REJECTED"


def test_aud006_old_tasklist_is_historical() -> None:
    row = {"historical": True, "authoritative": False, "as_of": "2026-07"}
    assert historical_tasklist_receipt([row])["status"] == "PROVEN"
    row["authoritative"] = True
    assert historical_tasklist_receipt([row])["status"] == "REJECTED"


def test_aud007_old_scoreboard_is_not_current() -> None:
    row = {"current_epoch": 8, "scoreboard_epoch": 7, "projected_as_current": False}
    assert epoch_scoreboard_receipt([row])["status"] == "PROVEN"
    row["projected_as_current"] = True
    assert epoch_scoreboard_receipt([row])["status"] == "REJECTED"


def test_aud008_missing_champion_is_nonmeasurable() -> None:
    row = {"champion": None, "status": "NON_MEASURABLE", "gain_claimed": False}
    assert champion_nonmeasurable_receipt([row])["status"] == "PROVEN"
    row["gain_claimed"] = True
    assert champion_nonmeasurable_receipt([row])["status"] == "REJECTED"


def test_aud009_partial_sample_is_excluded() -> None:
    row = {"sample_id": "45199", "status": "PARTIAL", "included_in_replay": False, "included_in_backtest": False, "classification": "incomplete"}
    assert partial_sample_exclusion_receipt([row])["status"] == "PROVEN"
    row["included_in_replay"] = True
    assert partial_sample_exclusion_receipt([row])["status"] == "REJECTED"


def test_aud010_rejected_inventory_stays_excluded() -> None:
    row = {"status": "REJECTED", "included_in_replay": False, "included_in_backtest": False, "reason": "invalid provenance"}
    assert rejected_inventory_exclusion_receipt([row])["status"] == "PROVEN"
    row["included_in_backtest"] = True
    assert rejected_inventory_exclusion_receipt([row])["status"] == "REJECTED"
