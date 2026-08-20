from __future__ import annotations

from pathlib import Path

from hl_observer.ops.pre_run_cross_venue_466_545 import (
    CROSS_VENUE_REQUIREMENTS,
    FACETS,
    evaluate_cross_venue_requirements,
)

ROOT = Path(__file__).resolve().parents[1]


def test_cross_venue_contient_16_exigences_et_80_facettes():
    assert len(CROSS_VENUE_REQUIREMENTS) == 16
    assert len(FACETS) == 5
    assert len({key for key, _ in CROSS_VENUE_REQUIREMENTS}) == 16


def test_tous_les_scenarios_cross_venue_sont_specifiques_et_fail_closed():
    result = evaluate_cross_venue_requirements(ROOT)
    assert result["category"] == "CROSS_VENUE"
    assert result["requirements_total"] == 16
    assert result["facets_total"] == 80
    assert result["requirements_done"] == 16
    assert result["facets_done"] == 80
    assert result["ok"] is True
    for row in result["requirements"]:
        assert row["ok"] is True
        assert all(row["facets"].values())
        assert row["evidence"]
        assert row["evidence_sha256"]
        assert row["source_mode"] == "CERTIFIED_ATOMIC_FOUR_SIDE_BOOK_V2"


def test_preuves_cross_venue_sont_hashes_et_distinctes():
    result = evaluate_cross_venue_requirements(ROOT)
    for row in result["requirements"]:
        assert row["key"]
        for digest in row["evidence_sha256"].values():
            assert len(digest) == 64
            int(digest, 16)
