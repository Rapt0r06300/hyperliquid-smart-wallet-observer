import pytest

from hl_observer.research.process_memory import (
    ProcessMemoryValidationError,
    append_process_record,
    candidate_memory_effect,
    load_process_records,
    process_memory_summary,
    validate_process_record,
)


def _record(**overrides):
    payload = {
        "record_id": "PM-1",
        "family": "lead_lag",
        "mechanism_signature": "binance-bbo-leads-hl",
        "context": ["high-liquidity"],
        "change_motif": "new-surface",
        "outcome": "FAILURE",
        "evidence_count": 8,
        "confidence": 0.95,
        "failure_reason": "coverage-gap",
        "success_evidence": None,
        "provenance": "runtime",
        "certifying": False,
        "retest_condition": "new synchronized capture",
    }
    payload.update(overrides)
    return payload


def test_schema_validation_and_append_only(tmp_path):
    normalized = validate_process_record(_record())
    assert normalized["family"] == "lead_lag"
    path = tmp_path / "memory.jsonl"
    append_process_record(path, normalized)
    assert load_process_records(path) == [normalized]
    with pytest.raises(ProcessMemoryValidationError):
        append_process_record(path, normalized)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_process_memory_can_never_be_marked_certifying():
    with pytest.raises(ProcessMemoryValidationError, match="cannot certify"):
        validate_process_record(_record(certifying=True))


def test_negative_memory_veto_positive_boost_and_retest_override():
    failures = [_record(record_id=f"PM-F{i}") for i in range(2)]
    candidate = {
        "family": "lead_lag",
        "mechanism_signature": "binance-bbo-leads-hl",
        "context": ["high-liquidity"],
    }
    effect = candidate_memory_effect(candidate, failures)
    assert effect["veto"] is True
    successes = [
        _record(
            record_id="PM-S",
            outcome="SUCCESS",
            confidence=0.9,
            success_evidence="positive OOS",
            failure_reason=None,
        )
    ]
    boosted = candidate_memory_effect(candidate, successes)
    assert 0 < boosted["boost"] <= 0.25
    retest = dict(candidate, retest_evidence=["new synchronized capture"])
    assert candidate_memory_effect(retest, failures)["veto"] is False


def test_compact_summary_reports_veto_motifs():
    records = [_record(record_id="PM-A"), _record(record_id="PM-B")]
    summary = process_memory_summary(records, family="lead_lag")
    assert summary["records"] == 2
    assert "binance-bbo-leads-hl" in summary["high_confidence_veto_motifs"]
