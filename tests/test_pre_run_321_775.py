from __future__ import annotations

import json
from pathlib import Path

from hl_observer.ops.pre_run_guard_321_775 import (
    BASE_COUNT,
    DERIVED_COUNT,
    DERIVED_END,
    DERIVED_START,
    FACETS,
    base_requirements,
    evaluate,
    proof_id,
)

ROOT = Path(__file__).resolve().parents[1]


def test_registry_is_exactly_91_requirements_times_5_facets() -> None:
    requirements = base_requirements()
    assert len(requirements) == BASE_COUNT == 91
    assert len(FACETS) == 5 and DERIVED_COUNT == 455 and DERIVED_START == 321 and DERIVED_END == 775


def test_derived_ids_are_contiguous_and_unique_321_to_775() -> None:
    ids = [proof_id(requirement.ordinal, facet_index) for requirement in base_requirements() for facet_index in range(len(FACETS))]
    assert ids == list(range(321, 776))
    assert len(ids) == len(set(ids)) == 455


def test_no_derived_proof_claims_historical_literal_recovery() -> None:
    result = evaluate(ROOT)
    assert result["exact_literal_reconstruction_claimed"] is False
    assert result["historical_literal_recovery"] == "TERMINAL_SOURCE_LOSS_HONEST"
    assert all(proof["historical_literal"] is False for proof in result["proofs"])
    assert all(proof["provenance"] == "DERIVED_TECHNICAL_REQUIREMENT" for proof in result["proofs"])


def test_all_91_requirements_and_455_facets_are_specifically_green() -> None:
    result = evaluate(ROOT)
    assert result["source_contract_ok"] is True and result["prior_1_320_assets_ok"] is True
    assert result["base_requirements_done"] == result["base_requirements_total"] == 91
    assert result["derived_proofs_done"] == result["derived_proofs_total"] == 455
    assert result["technical_done"] == 775 and result["next_derived_id"] is None
    assert result["technical_completion_claimed"] is True and result["complete"] is True
    assert result["status"] == "DONE_TECHNICAL_775_SOURCE_LOSS_HONEST" and result["ok"] is True
    assert len(result["evaluated_categories"]) == 12
    for category in result["evaluated_categories"]:
        assert result["category_progress"][category]["ok"] is True, category


def test_all_321_775_proofs_have_specific_hashed_evidence() -> None:
    result = evaluate(ROOT)
    assert len(result["proofs"]) == 455 and all(proof["ok"] is True for proof in result["proofs"])
    for proof in result["proofs"]:
        assert proof["evidence"] and proof["evidence_sha256"]
        assert proof["blocker"] is None
        for digest in proof["evidence_sha256"].values():
            assert len(digest) == 64
            int(digest, 16)


def test_remaining_546_775_is_exactly_46_requirements_230_facets() -> None:
    result = evaluate(ROOT)
    remaining = result["remaining_546_775"]
    assert remaining["requirements_done"] == remaining["requirements_total"] == 46
    assert remaining["facets_done"] == remaining["facets_total"] == 230
    assert remaining["ok"] is True


def test_gate_is_fail_closed_when_source_contract_is_missing(tmp_path: Path) -> None:
    result = evaluate(tmp_path)
    assert result["ok"] is False and result["source_contract_ok"] is False
    assert result["complete"] is False and result["technical_completion_claimed"] is False
    assert result["technical_done"] < 775


def test_status_manifest_ne_reconstruit_jamais_les_labels_perdus() -> None:
    status = json.loads((ROOT / "docs/PRE_RUN_775_CANONICAL_STATUS.json").read_text(encoding="utf-8"))
    assert status["literal_source_unrecoverable"] is True
    assert status["exact_literal_reconstruction_claimed"] is False
