from __future__ import annotations

from pathlib import Path

from hl_observer.ops.pre_run_lead_lag_396_465 import (
    FACETS,
    LEAD_LAG_REQUIREMENTS,
    evaluate_lead_lag_requirements,
)

ROOT = Path(__file__).resolve().parents[1]


def test_lead_lag_registry_is_exactly_14_requirements_times_5_facets() -> None:
    assert len(LEAD_LAG_REQUIREMENTS) == 14
    assert len(FACETS) == 5


def test_all_lead_lag_requirements_are_specifically_executable() -> None:
    result = evaluate_lead_lag_requirements(ROOT)
    assert result["category"] == "LEAD_LAG"
    assert result["requirements_total"] == 14
    assert result["requirements_done"] == 14
    assert result["facets_total"] == 70
    assert result["facets_done"] == 70
    assert result["ok"] is True


def test_every_lead_lag_requirement_has_five_green_facets_and_hashed_evidence() -> None:
    result = evaluate_lead_lag_requirements(ROOT)
    for row in result["requirements"]:
        assert row["ok"] is True, row
        assert set(row["facets"]) == set(FACETS)
        assert all(row["facets"].values()), row
        assert row["evidence"]
        assert set(row["evidence_sha256"]) == set(row["evidence"])
        for digest in row["evidence_sha256"].values():
            assert len(digest) == 64
            int(digest, 16)


def test_lead_lag_evidence_provenance_fails_closed_outside_repository(tmp_path: Path) -> None:
    result = evaluate_lead_lag_requirements(tmp_path)
    assert result["ok"] is False
    assert result["facets_done"] < result["facets_total"]
    assert all(
        row["facets"]["EVIDENCE_PROVENANCE"] is False
        for row in result["requirements"]
    )


def test_lead_lag_scenarios_do_not_claim_real_execution() -> None:
    result = evaluate_lead_lag_requirements(ROOT)
    forbidden = {"real_order", "exchange_order", "private_key", "signature"}
    serialized = repr(result).lower()
    assert not any(token in serialized for token in forbidden)
