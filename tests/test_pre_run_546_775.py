from __future__ import annotations

from pathlib import Path

from hl_observer.ops.pre_run_final_546_775 import CATEGORY_REQUIREMENTS, FACETS, evaluate_remaining_requirements

ROOT = Path(__file__).resolve().parents[1]


def test_registry_remaining_is_exactly_46_requirements_230_facets():
    assert sum(len(rows) for rows in CATEGORY_REQUIREMENTS.values()) == 46
    assert len(FACETS) == 5
    assert sum(len(rows) for rows in CATEGORY_REQUIREMENTS.values()) * len(FACETS) == 230


def test_all_remaining_546_775_are_specifically_executable_and_green():
    result = evaluate_remaining_requirements(ROOT)
    assert result["requirements_total"] == 46
    assert result["requirements_done"] == 46, result
    assert result["facets_total"] == 230
    assert result["facets_done"] == 230, result
    assert result["ok"] is True, result
    for category, row in result["categories"].items():
        assert row["ok"] is True, (category, row)
        for requirement in row["requirements"]:
            assert all(requirement["facets"].values()), requirement
            assert requirement["evidence_sha256"]
            assert all(len(value) == 64 for value in requirement["evidence_sha256"].values())
