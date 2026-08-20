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
    failures = []
    for category, row in result["categories"].items():
        for requirement in row["requirements"]:
            failed_facets = [name for name, value in requirement["facets"].items() if not value]
            if failed_facets:
                failures.append({
                    "category": category,
                    "key": requirement["key"],
                    "failed_facets": failed_facets,
                    "evidence": requirement["evidence"],
                })
    assert result["requirements_total"] == 46
    assert result["requirements_done"] == 46, failures
    assert result["facets_total"] == 230
    assert result["facets_done"] == 230, failures
    assert result["ok"] is True, failures
    for category, row in result["categories"].items():
        assert row["ok"] is True, (category, row)
        for requirement in row["requirements"]:
            assert all(requirement["facets"].values()), requirement
            assert requirement["evidence_sha256"]
            assert all(len(value) == 64 for value in requirement["evidence_sha256"].values())


def test_economic_memory_is_certified_only_after_durable_canonical_completion():
    family_source = (ROOT / "src/hl_observer/ops/family_economic_job.py").read_text(encoding="utf-8")
    completion_source = (ROOT / "src/hl_observer/ops/autonomous_completion.py").read_text(encoding="utf-8")

    worker_source = family_source.split("def execute_family_job", 1)[1]
    assert "record_family_economic_memory(" not in worker_source
    assert "PENDING_COMPLETION_GUARD" in worker_source

    completion_true = completion_source.index('result["completion_recorded"] = True')
    durable_write = completion_source.index("_atomic_json(result_path, result)", completion_true)
    memory_write = completion_source.index("_persist_post_completion_economic_memory(", durable_write)
    assert completion_true < durable_write < memory_write
    assert "JOB_RESULT disque non finalisé avant persistance de la mémoire économique" in completion_source
