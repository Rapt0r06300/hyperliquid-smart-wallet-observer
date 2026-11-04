from hl_observer.backtest.execution_realism import (
    execution_age_receipt,
    execution_commit_receipt,
    execution_cutoff_receipt,
    execution_duplicate_receipt,
    execution_finite_receipt,
    execution_realism_safety_receipt,
    execution_replay_receipt,
    execution_required_field_receipt,
    execution_retry_receipt,
)
from hl_observer.simulation.economic_proof_controls import (
    INDEPENDENT_AUDIT_SCHEMA,
    execution_to_economic_boundary_receipt,
)


def _economic_boundary():
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


def _join(receipt=None, economic=None):
    return execution_to_economic_boundary_receipt(
        receipt or execution_realism_safety_receipt(
            {"fill_probability": 0.5, "penalty_bps": 1.0, "latency_ms": 10.0}
        ),
        _economic_boundary() if economic is None else economic,
    )


def test_asf_hvr_0761_normal_fixture_joins_safely():
    assert _join()["status"] == "PROVEN"


def test_asf_hvr_0762_missing_execution_fixture_fails_closed():
    assert _join(execution_realism_safety_receipt({}))["status"] == "REJECTED"


def test_asf_hvr_0763_required_field_gate_is_forwarded():
    assert _join(execution_required_field_receipt({"coin": "BTC"}, field="coin"))["status"] == "PROVEN"
    assert _join(execution_required_field_receipt({}, field="coin"))["status"] == "REJECTED"


def test_asf_hvr_0764_finite_gate_is_forwarded():
    assert _join(execution_finite_receipt(1.0))["status"] == "PROVEN"
    assert _join(execution_finite_receipt(float("inf")))["status"] == "REJECTED"


def test_asf_hvr_0765_cutoff_gate_is_forwarded():
    assert _join(execution_cutoff_receipt(event_ts_ms=100, cutoff_ts_ms=100))["status"] == "PROVEN"
    assert _join(execution_cutoff_receipt(event_ts_ms=101, cutoff_ts_ms=100))["status"] == "REJECTED"


def test_asf_hvr_0766_age_gate_is_forwarded():
    assert _join(execution_age_receipt(event_ts_ms=100, oldest_allowed_ts_ms=100))["status"] == "PROVEN"
    assert _join(execution_age_receipt(event_ts_ms=99, oldest_allowed_ts_ms=100))["status"] == "REJECTED"


def test_asf_hvr_0767_duplicate_gate_is_forwarded():
    assert _join(execution_duplicate_receipt(event_ids=["a", "b"]))["status"] == "PROVEN"
    assert _join(execution_duplicate_receipt(event_ids=["a", "a"]))["status"] == "REJECTED"


def test_asf_hvr_0768_retry_gate_is_forwarded():
    assert _join(execution_retry_receipt(attempts=1, max_attempts=2, checkpoint_saved=True))["status"] == "PROVEN"
    assert _join(execution_retry_receipt(attempts=3, max_attempts=2, checkpoint_saved=True))["status"] == "REJECTED"


def test_asf_hvr_0769_replay_gate_is_forwarded():
    assert _join(execution_replay_receipt(outputs=[{"net": 1}, {"net": 1}]))["status"] == "PROVEN"
    assert _join(execution_replay_receipt(outputs=[{"net": 1}, {"net": 2}]))["status"] == "REJECTED"


def test_asf_hvr_0770_commit_gate_is_forwarded():
    assert _join(execution_commit_receipt(crashed=True, committed=False, checkpoint_saved=True))["status"] == "PROVEN"
    assert _join(execution_commit_receipt(crashed=True, committed=True, checkpoint_saved=False))["status"] == "REJECTED"


def test_asf_hvr_0771_economic_schema_is_required():
    economic = _economic_boundary()
    economic.pop("schema_version")
    assert _join(economic=economic)["status"] == "REJECTED"


def test_asf_hvr_0772_economic_hashes_are_required():
    economic = _economic_boundary()
    economic["data_sha256"] = ""
    assert _join(economic=economic)["status"] == "REJECTED"


def test_asf_hvr_0773_cutoff_is_required():
    economic = _economic_boundary()
    economic["cutoff_ts_ms"] = 0
    assert _join(economic=economic)["status"] == "REJECTED"


def test_asf_hvr_0774_paper_only_boundary_is_required():
    economic = _economic_boundary()
    economic["paper_only"] = False
    assert _join(economic=economic)["status"] == "REJECTED"


def test_asf_hvr_0775_real_execution_is_rejected():
    economic = _economic_boundary()
    economic["real_execution"] = True
    assert _join(economic=economic)["status"] == "REJECTED"


def test_asf_hvr_0776_unknown_economic_status_is_rejected():
    economic = _economic_boundary()
    economic["economic_proof_status"] = "PROVEN_WITHOUT_DATA"
    assert _join(economic=economic)["status"] == "REJECTED"


def test_asf_hvr_0777_join_never_promotes():
    assert _join()["promotion"] == "DISABLED_UNTIL_REVIEW"


def test_asf_hvr_0778_join_is_explicitly_paper_read_only():
    assert _join()["paper_read_only"] is True
    assert _join()["real_execution"] is False


def test_asf_hvr_0779_join_reports_both_statuses():
    result = _join()
    assert result["execution_status"] == "PROVEN"
    assert result["economic_status"] == "PROVEN"


def test_asf_hvr_0780_join_rejects_unproven_economic_boundary():
    economic = _economic_boundary()
    economic["freeze_sha256"] = None
    result = _join(economic=economic)
    assert result["status"] == "REJECTED"
    assert result["fail_closed"] is True
