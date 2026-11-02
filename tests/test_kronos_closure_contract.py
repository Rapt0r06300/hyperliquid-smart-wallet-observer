from __future__ import annotations

from copy import deepcopy

from hl_observer.research.kronos_context_contract import (
    build_kronos_closure_report,
)


def _evidence() -> dict[str, object]:
    return {
        "context_receipt": {
            "status": "READY",
            "paper_read_only": True,
            "real_execution": False,
            "receipt_sha256": "a" * 64,
        },
        "preregistration": {
            "status": "PREREGISTERED",
            "paper_read_only": True,
            "real_execution": False,
            "protocol_sha256": "b" * 64,
        },
        "post_training_cutoff": True,
        "missing_fields_not_zeroed": True,
        "forecast_summary": {
            "status": "MEASURED",
            "sample_count": 12,
            "mean": "0.125",
        },
        "replay": {
            "train": {"frozen": True, "receipt_sha256": "c" * 64},
            "oos": {"frozen": True, "receipt_sha256": "d" * 64},
            "forward": {"frozen": True, "receipt_sha256": "e" * 64},
        },
        "report": {
            "html_sha256": "f" * 64,
            "forecast_realized_sha256": "1" * 64,
        },
        "claims": {
            "repo_model_tokenizer_license_frozen": True,
            "dependency_hashes": True,
            "cutoff_frozen": True,
            "protocol_preregistered": True,
            "post_training_cutoff": True,
            "sample_count_mean_verified": True,
            "missing_fields_not_zeroed": True,
            "train_oos_forward": True,
            "forecast_realized_report": True,
            "same_costs": True,
            "baseline_comparison": True,
            "same_episodes": True,
            "trial_accounting": True,
            "append_only_results": True,
            "html_report": True,
            "uncertainty_from_retained_trajectories": True,
        },
    }


def test_kronos_closure_requires_frozen_replay_and_measured_summary() -> None:
    report = build_kronos_closure_report(_evidence())

    assert report["status"] == "PROVEN"
    assert report["claims"]["train_oos_forward"] is True
    assert report["paper_read_only"] is True


def test_kronos_closure_never_turns_missing_forecast_into_zero() -> None:
    evidence = deepcopy(_evidence())
    evidence["forecast_summary"]["mean"] = None

    report = build_kronos_closure_report(evidence)

    assert report["status"] == "NOT_PROVEN"
    assert "forecast_summary.mean" in report["invalid"]
    assert report["claims"] == {}
