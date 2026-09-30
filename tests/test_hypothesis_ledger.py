from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.research.hypothesis_ledger import (
    HypothesisValidationError,
    append_record,
    challenger_required,
    compact_status,
    load_records,
    novelty_score,
    rediscovery_required,
    semantic_fingerprint,
    validate_record,
)


def record(
    *,
    record_id: str,
    hypothesis_id: str = "H-1",
    family: str = "lead_lag",
    stage: str = "DISCOVERY",
    mechanism: str = "asynchronous price discovery",
    data_surfaces: list[str] | None = None,
    temporal_operator: str = "lagged cross-correlation",
    conditioning: list[str] | None = None,
    prediction_target: str = "30s executable markout",
    execution_translation: str = "paper taker after signal",
    change_class: str = "NEW_MECHANISM",
    parent_hypothesis_id: str | None = None,
    verdict: str | None = None,
    economic_progress: dict | None = None,
    baseline: bool = False,
    created_at_utc: str = "2026-09-10T12:00:00Z",
    controller_action: str | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "record_id": record_id,
        "created_at_utc": created_at_utc,
        "hypothesis_id": hypothesis_id,
        "family": family,
        "parent_hypothesis_id": parent_hypothesis_id,
        "stage": stage,
        "mechanism": mechanism,
        "data_surfaces": data_surfaces or ["binance_bbo", "hl_bbo"],
        "temporal_operator": temporal_operator,
        "conditioning": conditioning or ["liquid regime"],
        "prediction_target": prediction_target,
        "execution_translation": execution_translation,
        "change_class": change_class,
        "rationale": "Price discovery may arrive on one venue first.",
        "falsification_test": "Reject if post-cost held-out markout has no positive headroom.",
        "source_refs": ["paper:example"],
        "experiment_ids": [],
        "scientific_signatures": [],
        "trial_count": 0,
        "verdict": verdict,
        "economic_progress": economic_progress or {},
        "notes": None,
        "baseline": baseline,
        "controller_action": controller_action,
    }


def test_validate_record_normalizes_sets_and_generates_audit_fields() -> None:
    payload = record(record_id="R-1")
    payload.pop("record_id")
    payload.pop("created_at_utc")
    payload["data_surfaces"] = ["HL_BBO", "binance_bbo", "hl_bbo"]
    result = validate_record(payload)
    assert result["record_id"].startswith("R-")
    assert result["created_at_utc"].endswith("Z")
    assert result["data_surfaces"] == ["binance_bbo", "HL_BBO"]


def test_validate_record_rejects_unsafe_or_missing_fields() -> None:
    payload = record(record_id="R-1")
    payload["family"] = "funding_carry"
    with pytest.raises(HypothesisValidationError):
        validate_record(payload)
    payload = record(record_id="R-1")
    payload["data_surfaces"] = []
    with pytest.raises(HypothesisValidationError):
        validate_record(payload)


def test_semantic_fingerprint_ignores_list_order_and_parameter_metadata() -> None:
    left = record(record_id="R-1", conditioning=["volatile", "liquid"])
    right = record(record_id="R-2", conditioning=["liquid", "volatile"])
    right["trial_count"] = 999
    right["verdict"] = "REJECT"
    right["economic_progress"] = {"net_usd_per_day": -1.0}
    assert semantic_fingerprint(left) == semantic_fingerprint(right)


def test_validate_record_tracks_head_and_controller_action_without_affecting_semantics() -> None:
    left = record(record_id="R-1")
    right = record(record_id="R-2")
    left["base_sha"] = "a" * 40
    left["controller_action"] = "PIVOT"
    right["base_sha"] = "b" * 40
    right["controller_action"] = "IMPROVE"
    validated = validate_record(left)
    assert validated["base_sha"] == "a" * 40
    assert validated["controller_action"] == "PIVOT"
    assert semantic_fingerprint(left) == semantic_fingerprint(right)
    bad = record(record_id="R-3")
    bad["controller_action"] = "LOOP"
    with pytest.raises(HypothesisValidationError):
        validate_record(bad)


def test_novelty_score_duplicate_zero_and_new_mechanism_high() -> None:
    prior = record(record_id="R-1")
    duplicate = record(record_id="R-2")
    novel = record(
        record_id="R-3",
        mechanism="wallet toxicity conditioned queue depletion",
        data_surfaces=["wallet_fills", "hl_l2"],
        temporal_operator="event-time hazard",
        conditioning=["toxic wallet", "thin ask"],
        prediction_target="5s fill-conditioned price move",
        execution_translation="paper maker queue join",
    )
    assert novelty_score(duplicate, [prior]) == 0.0
    assert 0.0 <= novelty_score(novel, [prior]) <= 1.0
    assert novelty_score(novel, [prior]) > 0.7


def test_append_is_append_only_and_duplicate_record_id_is_rejected(tmp_path: Path) -> None:
    ledger = tmp_path / "HYPOTHESIS_LEDGER.jsonl"
    first = record(record_id="R-1")
    second = record(record_id="R-2", hypothesis_id="H-2", mechanism="wallet anticipation")
    append_record(ledger, first)
    before = ledger.read_bytes()
    append_record(ledger, second)
    after = ledger.read_bytes()
    assert after.startswith(before)
    assert len(load_records(ledger)) == 2
    with pytest.raises(HypothesisValidationError):
        append_record(ledger, first)


def test_load_records_filters_family_and_rejects_corrupt_history(tmp_path: Path) -> None:
    ledger = tmp_path / "HYPOTHESIS_LEDGER.jsonl"
    append_record(ledger, record(record_id="R-1", family="lead_lag"))
    append_record(
        ledger,
        record(
            record_id="R-2",
            hypothesis_id="H-CV",
            family="cross_venue_dislocation_v2",
        ),
    )
    assert [item["record_id"] for item in load_records(ledger, "lead_lag")] == ["R-1"]
    ledger.write_text(ledger.read_text(encoding="utf-8") + "{bad json}\n", encoding="utf-8")
    with pytest.raises(HypothesisValidationError):
        load_records(ledger)


def test_two_parameter_only_nonprogress_iterations_force_rediscovery() -> None:
    history = [
        record(
            record_id="R-1",
            stage="EXPLOIT",
            change_class="PARAMETER_ONLY",
            economic_progress={"comparable": True, "delta_net_usd_per_day": 0.0},
            created_at_utc="2026-09-10T12:00:00Z",
        ),
        record(
            record_id="R-2",
            stage="EXPLOIT",
            change_class="PARAMETER_ONLY",
            economic_progress={"comparable": True, "delta_net_usd_per_day": -0.1},
            created_at_utc="2026-09-10T12:01:00Z",
        ),
    ]
    assert rediscovery_required(history, "H-1") is True


def test_positive_second_parameter_iteration_does_not_force_rediscovery() -> None:
    history = [
        record(
            record_id="R-1",
            stage="EXPLOIT",
            change_class="PARAMETER_ONLY",
            economic_progress={"comparable": True, "delta_net_usd_per_day": 0.0},
            created_at_utc="2026-09-10T12:00:00Z",
        ),
        record(
            record_id="R-2",
            stage="EXPLOIT",
            change_class="PARAMETER_ONLY",
            economic_progress={"comparable": True, "delta_net_usd_per_day": 0.5},
            created_at_utc="2026-09-10T12:01:00Z",
        ),
    ]
    assert rediscovery_required(history, "H-1") is False


def test_two_nonpositive_headroom_evaluations_force_rediscovery_across_lineage() -> None:
    history = [
        record(
            record_id="R-1",
            hypothesis_id="H-root",
            stage="EXPLOIT",
            change_class="NEW_MECHANISM",
            economic_progress={"net_headroom_usd_per_day": -1.0},
            created_at_utc="2026-09-10T12:00:00Z",
        ),
        record(
            record_id="R-2",
            hypothesis_id="H-child",
            parent_hypothesis_id="H-root",
            stage="EXPLOIT",
            change_class="MODEL",
            economic_progress={"net_headroom_usd_per_day": 0.0},
            created_at_utc="2026-09-10T12:01:00Z",
        ),
    ]
    assert rediscovery_required(history, "H-child") is True


def test_three_consecutive_improves_require_champion_challenger() -> None:
    history = [
        record(
            record_id=f"R-{i}",
            stage="EXPLOIT",
            change_class="MODEL",
            controller_action="IMPROVE",
            economic_progress={"comparable": True, "delta_net_usd_per_day": 0.1 * i},
            created_at_utc=f"2026-09-10T12:0{i}:00Z",
        )
        for i in range(1, 4)
    ]
    assert challenger_required(history, "H-1") is True


def test_freeze_or_pivot_resets_champion_challenger_counter() -> None:
    improves = [
        record(
            record_id=f"R-{i}",
            stage="EXPLOIT",
            change_class="MODEL",
            controller_action="IMPROVE",
            created_at_utc=f"2026-09-10T12:0{i}:00Z",
        )
        for i in range(1, 4)
    ]
    frozen = record(
        record_id="R-4",
        stage="FREEZE",
        change_class="MODEL",
        controller_action="STOP",
        created_at_utc="2026-09-10T12:04:00Z",
    )
    assert challenger_required([*improves, frozen], "H-1") is False


def test_compact_status_counts_baselines_trials_and_latest() -> None:
    history = [
        {**record(record_id="R-1", baseline=True), "trial_count": 10},
        {
            **record(
                record_id="R-2",
                hypothesis_id="H-2",
                stage="TOURNAMENT",
                change_class="REPRESENTATION",
                created_at_utc="2026-09-10T12:02:00Z",
            ),
            "trial_count": 7,
        },
    ]
    result = compact_status(history, "lead_lag")
    assert result["records"] == 2
    assert result["unique_hypotheses"] == 2
    assert result["baseline_records"] == 1
    assert result["trial_count"] == 17
    assert result["latest"]["hypothesis_id"] == "H-2"
    assert isinstance(result["rediscovery_required"], bool)
    assert isinstance(result["challenger_required"], bool)


def test_ledger_is_jsonl_machine_readable(tmp_path: Path) -> None:
    ledger = tmp_path / "HYPOTHESIS_LEDGER.jsonl"
    append_record(ledger, record(record_id="R-1"))
    line = ledger.read_text(encoding="utf-8").strip()
    decoded = json.loads(line)
    assert decoded["record_id"] == "R-1"
