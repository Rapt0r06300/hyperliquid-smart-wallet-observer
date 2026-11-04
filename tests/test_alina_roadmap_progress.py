from __future__ import annotations

from tools.alina_roadmap_progress import progress_by_family


def test_progress_by_family_keeps_ecos_separate_from_global_closure():
    tasks = [
        {"id": "T001"},
        {"id": "ECO-001"},
        {"id": "ECO-002"},
        {"id": "LCH-001"},
    ]

    report = progress_by_family(tasks, {"T001", "ECO-001"})

    assert report["ECO"] == {"total": 2, "verified_done": 1, "percent": 50.0, "closure_allowed": False}
    assert report["T001"] == {"total": 1, "verified_done": 1, "percent": 100.0, "closure_allowed": True}
