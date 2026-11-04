from hl_observer.copying.copy_vault_wallet_controls import (
    desync_quarantine_receipt,
    first_decision_wallet_discovery_receipt,
    hyperliquid_budget_calibration_receipt,
    leader_style_change_receipt,
    mirror_canonical_path_receipt,
    realtime_accessible_selection_receipt,
    shortlist_justification_receipt,
    top500_survivorship_receipt,
    vault_master_subaccount_receipt,
    watchlist_consent_receipt,
)


def test_lch201_wallet_is_discovered_before_decision() -> None:
    state = {"decision_id": "d1", "wallet_id": "w1", "discovered_before_decision": True, "source_manifest": "m1"}
    assert first_decision_wallet_discovery_receipt(state)["status"] == "PROVEN"
    state["discovered_before_decision"] = False
    assert first_decision_wallet_discovery_receipt(state)["status"] == "UNMEASURABLE"


def test_lch202_wallet_roles_are_distinct() -> None:
    rows = [{"address": "v", "role": "vault"}, {"address": "m", "role": "master"}, {"address": "s", "role": "subaccount", "parent_address": "m"}]
    assert vault_master_subaccount_receipt(rows)["status"] == "PROVEN"
    assert vault_master_subaccount_receipt([{"address": "s", "role": "subaccount"}])["status"] == "UNMEASURABLE"


def test_lch203_shortlist_has_justification() -> None:
    row = {"wallet_id": "w1", "rank": 1, "justification_ref": "score:1"}
    assert shortlist_justification_receipt([row])["status"] == "PROVEN"
    del row["justification_ref"]
    assert shortlist_justification_receipt([row])["status"] == "UNMEASURABLE"


def test_lch204_top500_controls_survivorship() -> None:
    state = {"universe_count": 1000, "selected_count": 500, "full_universe_observed": True, "survivorship_filter_applied": False}
    assert top500_survivorship_receipt(state)["status"] == "PROVEN"
    state["full_universe_observed"] = False
    assert top500_survivorship_receipt(state)["status"] == "REJECTED"


def test_lch205_selection_is_realtime_accessible() -> None:
    assert realtime_accessible_selection_receipt([{"real_time_access": True, "age_ms": 10, "source": "ws"}])["status"] == "PROVEN"
    assert realtime_accessible_selection_receipt([{"real_time_access": True, "age_ms": 100_000, "source": "ws"}])["status"] == "REJECTED"


def test_lch206_budget_calibration_is_observed() -> None:
    assert hyperliquid_budget_calibration_receipt([{"requests": 2, "budget": 10, "remaining": 8}])["status"] == "PROVEN"
    assert hyperliquid_budget_calibration_receipt([{"requests": 11, "budget": 10, "remaining": 0}])["status"] == "UNMEASURABLE"


def test_lch207_detects_leader_style_change() -> None:
    rows = [{"style": "maker", "observed_at_ms": 1}, {"style": "taker", "observed_at_ms": 2}]
    result = leader_style_change_receipt(rows)
    assert result["status"] == "PROVEN"
    assert result["changed"] is True


def test_lch208_desync_is_quarantined() -> None:
    assert desync_quarantine_receipt({"desync": True, "quarantined": True, "reconstruction_ref": "r1"})["status"] == "PROVEN"
    assert desync_quarantine_receipt({"desync": True, "quarantined": False})["status"] == "REJECTED"


def test_lch209_mirror_uses_canonical_pipeline() -> None:
    state = {"mirror_path": "canonical", "canonical_path": "canonical", "paper_read_only": True}
    assert mirror_canonical_path_receipt(state)["status"] == "PROVEN"
    state["mirror_path"] = "fork"
    assert mirror_canonical_path_receipt(state)["status"] == "REJECTED"


def test_lch210_watchlist_consent_is_explicit() -> None:
    row = {"wallet_id": "w1", "consent": True, "consent_ref": "consent:1"}
    assert watchlist_consent_receipt([row])["status"] == "PROVEN"
    row["consent"] = False
    assert watchlist_consent_receipt([row])["status"] == "REJECTED"
