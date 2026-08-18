from __future__ import annotations

import json
from pathlib import Path

from hl_observer.ops.pre_run_guard_321_775 import BASE_COUNT, DERIVED_COUNT, DERIVED_END, DERIVED_START, FACETS, base_requirements, evaluate, proof_id

ROOT = Path(__file__).resolve().parents[1]


def test_registry_is_exactly_91_requirements_times_5_facets() -> None:
    requirements = base_requirements()
    assert len(requirements) == BASE_COUNT == 91
    assert len(FACETS) == 5
    assert DERIVED_COUNT == 455
    assert DERIVED_START == 321
    assert DERIVED_END == 775


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


def test_current_progress_is_honest_395_with_copy_specific_only() -> None:
    result = evaluate(ROOT)
    assert result["source_contract_ok"] is True
    assert result["prior_1_320_assets_ok"] is True
    assert result["base_requirements_done"] == 15
    assert result["derived_proofs_done"] == 75
    assert result["technical_done"] == 395
    assert result["next_derived_id"] == 396
    assert result["technical_completion_claimed"] is False
    assert result["complete"] is False
    assert result["status"] == "IN_PROGRESS_TECHNICAL_775_SOURCE_LOSS_HONEST"
    assert result["ok"] is True
    assert result["category_progress"]["COPY_VAULT"]["ok"] is True


def test_future_categories_are_explicitly_incomplete_not_generic_file_green() -> None:
    result = evaluate(ROOT)
    future = [proof for proof in result["proofs"] if proof["id"] >= 396]
    assert future
    assert all(proof["ok"] is False for proof in future)
    assert all(proof["blocker"] == "CATEGORY_NOT_YET_SPECIFICALLY_VERIFIED" for proof in future)
    assert all(not proof["evidence"] for proof in future)


def test_copy_proofs_have_specific_hashed_evidence() -> None:
    result = evaluate(ROOT)
    copy = [proof for proof in result["proofs"] if 321 <= proof["id"] <= 395]
    assert len(copy) == 75
    assert all(proof["ok"] is True for proof in copy)
    for proof in copy:
        assert proof["evidence"]
        assert proof["evidence_sha256"]
        for digest in proof["evidence_sha256"].values():
            assert len(digest) == 64
            int(digest, 16)


def test_gate_is_fail_closed_when_source_contract_is_missing(tmp_path: Path) -> None:
    result = evaluate(tmp_path)
    assert result["ok"] is False
    assert result["source_contract_ok"] is False
    assert result["technical_completion_claimed"] is False
    assert result["technical_done"] < 395


def test_status_manifest_still_denies_literal_reconstruction() -> None:
    status = json.loads((ROOT / "docs/PRE_RUN_775_CANONICAL_STATUS.json").read_text(encoding="utf-8"))
    assert status["literal_source_unrecoverable"] is True
    assert status["exact_literal_reconstruction_claimed"] is False
    assert status["technical_completion_claimed"] is False
