from hl_observer.risk.copy_vault_safety_controls import (
    circuit_breaker_rearm_receipt,
    enabled_module_budget_receipt,
    error_report_redaction_receipt,
    finite_quota_receipt,
    hard_stop_consistency_receipt,
    non_negative_stop_receipt,
    risk_signal_conflict_receipt,
    score_guard_receipt,
    source_failure_fallback_receipt,
    venue_filter_receipt,
)


def test_bug_191_rearm_requires_every_proof():
    assert circuit_breaker_rearm_receipt(
        proof_valid=True,
        cooldown_elapsed=True,
        health_fresh=True,
        operator_acknowledged=True,
    )["status"] == "PROVEN"
    assert circuit_breaker_rearm_receipt(
        proof_valid=False,
        cooldown_elapsed=True,
        health_fresh=True,
        operator_acknowledged=True,
    )["status"] == "REJECTED"


def test_bug_192_risk_veto_wins_over_positive_signal():
    receipt = risk_signal_conflict_receipt(risk_veto=True, signal_positive=True)
    assert receipt["decision"] == "DENY"
    assert receipt["risk_veto_wins"] is True


def test_bug_193_nan_quota_is_rejected():
    assert finite_quota_receipt(quota=10, maximum=100)["status"] == "PROVEN"
    assert finite_quota_receipt(quota=float("nan"), maximum=100)["status"] == "REJECTED"


def test_bug_194_negative_stop_is_rejected():
    assert non_negative_stop_receipt(stop_tolerance=0)["status"] == "PROVEN"
    assert non_negative_stop_receipt(stop_tolerance=-1)["status"] == "REJECTED"


def test_bug_195_disabled_module_gets_no_budget():
    assert enabled_module_budget_receipt(module_enabled=True, budget=1)["status"] == "PROVEN"
    assert enabled_module_budget_receipt(module_enabled=False, budget=1)["status"] == "REJECTED"


def test_bug_196_cli_and_ui_hard_stop_must_match():
    assert hard_stop_consistency_receipt(cli_stop=5, ui_stop=5)["status"] == "PROVEN"
    assert hard_stop_consistency_receipt(cli_stop=5, ui_stop=6)["status"] == "REJECTED"


def test_bug_197_score_change_requires_guard():
    assert score_guard_receipt(score_before=1, score_after=2, guard_approved=True)["status"] == "PROVEN"
    assert score_guard_receipt(score_before=1, score_after=2, guard_approved=False)["status"] == "REJECTED"


def test_bug_198_source_failure_cannot_use_permissive_fallback():
    assert source_failure_fallback_receipt(
        source_ok=False,
        fallback_requested=True,
        explicit_conservative_fallback=True,
        fail_closed=True,
    )["status"] == "PROVEN"
    assert source_failure_fallback_receipt(
        source_ok=False,
        fallback_requested=True,
        explicit_conservative_fallback=False,
        fail_closed=False,
    )["status"] == "REJECTED"


def test_bug_199_venue_filter_requires_declared_allowed_venue():
    assert venue_filter_receipt(venue="hyperliquid", category="perp", allowed_venues=["hyperliquid"])["status"] == "PROVEN"
    assert venue_filter_receipt(venue="", category="perp", allowed_venues=["hyperliquid"])["status"] == "REJECTED"


def test_bug_200_error_report_rejects_secrets():
    assert error_report_redaction_receipt(error_message="paper audit failed", sensitive_values=[])["status"] == "PROVEN"
    assert error_report_redaction_receipt(error_message="private_key=abc", sensitive_values=[])["status"] == "REJECTED"
