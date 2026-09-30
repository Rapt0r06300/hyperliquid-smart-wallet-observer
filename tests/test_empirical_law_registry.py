from __future__ import annotations

from dataclasses import asdict
from datetime import date

from hl_observer.research.empirical_law_registry import (
    EMPIRICAL_LAW_REGISTRY_IS_ACTIVE_SCOPE_AUTHORITY,
    EvidenceQuality,
    build_record,
    failed_hypothesis_ids,
    negative_law_reopen_allowed,
)
from hl_observer.research.empirical_memory import EMPIRICAL_MEMORY_IS_ACTIVE_SCOPE_AUTHORITY
from hl_observer.research.lois_mesurees import LOIS, loi
from hl_observer.strategies.active_scope import strategy_can_materialize


def test_v5_record_exposes_required_machine_fields() -> None:
    record = build_record(loi("copy_global"), as_of=date(2026, 9, 10))
    assert set(asdict(record)) >= {
        "law_id", "hypothesis_family", "verdict", "measured_value", "measured_at",
        "dataset_id", "dataset_hash", "experiment_id", "git_sha", "cost_model_id",
        "source_refs", "source_hashes", "evidence_quality", "last_verified",
        "retest_after", "invalidated_if", "condition_de_reouverture",
        "scope_status_at_measurement",
    }


def test_unrecovered_historical_law_is_kept_but_downgraded() -> None:
    record = build_record(loi("lead_lag"), as_of=date(2026, 9, 10))
    assert record.law_id == "lead_lag"
    assert record.hypothesis_family == "lead_lag"
    assert record.source_refs
    assert record.dataset_hash is None
    assert record.evidence_quality is EvidenceQuality.HISTORICAL_UNVERIFIED


def test_confirmed_historical_carry_cannot_reactivate_disabled_scope() -> None:
    record = build_record(loi("carry_delta_neutre"), as_of=date(2026, 9, 10))
    assert record.verdict == "CONFIRME"
    assert record.active_scope_authority is False
    assert EMPIRICAL_LAW_REGISTRY_IS_ACTIVE_SCOPE_AUTHORITY is False
    assert EMPIRICAL_MEMORY_IS_ACTIVE_SCOPE_AUTHORITY is False
    assert strategy_can_materialize("funding_carry") is False


def test_negative_law_reopens_only_after_trigger_plus_new_information() -> None:
    law = loi("copy_global")
    assert law is not None
    assert not negative_law_reopen_allowed(
        law, retest_condition_triggered=False, new_data_available=True
    )
    assert not negative_law_reopen_allowed(
        law, retest_condition_triggered=True,
        new_data_available=False, new_physical_mechanism=False,
    )
    assert negative_law_reopen_allowed(
        law, retest_condition_triggered=True, new_data_available=True
    )


def test_failed_hypotheses_remain_visible_for_multiple_testing() -> None:
    failed = failed_hypothesis_ids(LOIS)
    assert "copy_global" in failed
    assert "lead_lag" in failed
    assert "market_making_spread" in failed
    assert "carry_delta_neutre" not in failed
