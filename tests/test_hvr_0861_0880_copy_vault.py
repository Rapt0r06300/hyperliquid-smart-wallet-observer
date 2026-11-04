from hl_observer.simulation.economic_proof_controls import (
    INDEPENDENT_AUDIT_SCHEMA,
    economic_proof_safety_receipt,
    proof_age_receipt,
    proof_balance_receipt,
    proof_commit_receipt,
    proof_conversion_receipt,
    proof_concurrent_write_receipt,
    proof_cutoff_receipt,
    proof_duplicate_receipt,
    proof_field_type_receipt,
    proof_fill_duplicate_receipt,
    proof_finite_receipt,
    proof_funding_sign_receipt,
    proof_mark_liquidability_receipt,
    proof_null_field_receipt,
    proof_partial_close_receipt,
    proof_rejection_no_debit_receipt,
    proof_replay_receipt,
    proof_required_field_receipt,
    proof_retry_receipt,
    proof_total_close_release_receipt,
)


def _proof():
    return {
        "schema_version": INDEPENDENT_AUDIT_SCHEMA,
        "family": "copy_vault",
        "data_sha256": "d" * 64,
        "code_sha256": "c" * 64,
        "freeze_sha256": "f" * 64,
        "cutoff_ts_ms": 100,
        "paper_only": True,
        "real_execution": False,
        "economic_proof_status": "UNMEASURABLE",
    }


def test_hvr_0861_economic_proof_baseline_is_safe():
    assert economic_proof_safety_receipt(_proof())["status"] == "PROVEN"
    assert economic_proof_safety_receipt({})["status"] == "REJECTED"


def test_hvr_0862_required_field():
    assert proof_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert proof_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0863_null_field():
    assert proof_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert proof_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0864_field_type():
    assert proof_field_type_receipt({"amount": 1.0}, field="amount", expected_type=float)["status"] == "PROVEN"
    assert proof_field_type_receipt({"amount": "1"}, field="amount", expected_type=float)["status"] == "REJECTED"


def test_hvr_0865_finite_value():
    assert proof_finite_receipt(1.5)["status"] == "PROVEN"
    assert proof_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0866_cutoff_boundary():
    assert proof_cutoff_receipt(event_ts_ms=100, cutoff_ts_ms=100)["status"] == "PROVEN"
    assert proof_cutoff_receipt(event_ts_ms=101, cutoff_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0867_old_event():
    assert proof_age_receipt(event_ts_ms=100, oldest_allowed_ts_ms=100)["status"] == "PROVEN"
    assert proof_age_receipt(event_ts_ms=99, oldest_allowed_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0868_duplicate_event():
    assert proof_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert proof_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0869_retry_is_bounded():
    assert proof_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert proof_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0870_replay_is_deterministic():
    assert proof_replay_receipt(outputs=[{"net": 1}, {"net": 1}])["status"] == "PROVEN"
    assert proof_replay_receipt(outputs=[{"net": 1}, {"net": 2}])["status"] == "REJECTED"


def test_hvr_0871_train_oos_forward_are_not_replaced_by_fill_ids():
    assert proof_fill_duplicate_receipt(fill_ids=["f1", "f2"])["status"] == "PROVEN"
    assert proof_fill_duplicate_receipt(fill_ids=["f1", "f1"])["status"] == "REJECTED"


def test_hvr_0872_rejection_has_no_debit():
    assert proof_rejection_no_debit_receipt(balance_before=100, balance_after=100, rejected=True)["status"] == "PROVEN"
    assert proof_rejection_no_debit_receipt(balance_before=100, balance_after=99, rejected=True)["status"] == "REJECTED"


def test_hvr_0873_partial_close_is_conserved():
    assert proof_partial_close_receipt(position_before=10, close_quantity=4, position_after=6)["status"] == "PROVEN"
    assert proof_partial_close_receipt(position_before=10, close_quantity=10, position_after=0)["status"] == "REJECTED"


def test_hvr_0874_total_close_releases_position():
    assert proof_total_close_release_receipt(position_before=10, released_quantity=10, position_after=0)["status"] == "PROVEN"
    assert proof_total_close_release_receipt(position_before=10, released_quantity=9, position_after=1)["status"] == "REJECTED"


def test_hvr_0875_slippage_edge_is_not_a_liquidability_mark():
    assert proof_mark_liquidability_receipt(mark=100, liquidatable=True)["status"] == "PROVEN"
    assert proof_mark_liquidability_receipt(mark=float("inf"), liquidatable=True)["status"] == "REJECTED"


def test_hvr_0876_correlated_wallet_balance_is_fail_closed():
    assert proof_balance_receipt(balance=100, equity=110, reserved=5)["status"] == "PROVEN"
    assert proof_balance_receipt(balance=100, equity=90, reserved=0)["status"] == "REJECTED"


def test_hvr_0877_funding_sign_is_explicit():
    assert proof_funding_sign_receipt(funding_pnl=-2, funding_rate=0.02, position_size=100)["status"] == "PROVEN"
    assert proof_funding_sign_receipt(funding_pnl=2, funding_rate=0.02, position_size=100)["status"] == "REJECTED"


def test_hvr_0878_conversion_is_reconciled():
    assert proof_conversion_receipt(source_value=10, converted_value=20, conversion_rate=2)["status"] == "PROVEN"
    assert proof_conversion_receipt(source_value=10, converted_value=21, conversion_rate=2)["status"] == "REJECTED"


def test_hvr_0879_commit_requires_receipt():
    assert proof_commit_receipt(prepared=True, committed=True, receipt_id="r1")["status"] == "PROVEN"
    assert proof_commit_receipt(prepared=True, committed=False, receipt_id="r1")["status"] == "REJECTED"


def test_hvr_0880_concurrent_writes_are_serialized():
    assert proof_concurrent_write_receipt(writers=2, accepted_versions=[1, 2], unique_commit_ids=["a", "b"])["status"] == "PROVEN"
    assert proof_concurrent_write_receipt(writers=2, accepted_versions=[1, 1], unique_commit_ids=["a", "b"])["status"] == "REJECTED"
