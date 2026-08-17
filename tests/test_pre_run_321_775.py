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
    assert len(FACETS) == 5
    assert DERIVED_COUNT == 455
    assert DERIVED_START == 321
    assert DERIVED_END == 775


def test_derived_ids_are_contiguous_and_unique_321_to_775() -> None:
    ids = [
        proof_id(requirement.ordinal, facet_index)
        for requirement in base_requirements()
        for facet_index in range(len(FACETS))
    ]
    assert ids == list(range(321, 776))
    assert len(ids) == len(set(ids)) == 455


def test_no_derived_proof_claims_historical_literal_recovery() -> None:
    result = evaluate(ROOT)
    assert result["exact_literal_reconstruction_claimed"] is False
    assert result["historical_literal_recovery"] == "TERMINAL_SOURCE_LOSS_HONEST"
    assert all(proof["historical_literal"] is False for proof in result["proofs"])
    assert all(proof["provenance"] == "DERIVED_TECHNICAL_REQUIREMENT" for proof in result["proofs"])


def test_current_repository_proves_all_455_derived_controls() -> None:
    result = evaluate(ROOT)
    assert result["source_contract_ok"] is True
    assert result["prior_1_320_assets_ok"] is True
    assert result["base_requirements_done"] == 91
    assert result["derived_proofs_done"] == 455
    assert result["technical_done"] == 775
    assert result["technical_completion_claimed"] is True
    assert result["status"] == "DONE_TECHNICAL_775_SOURCE_LOSS_HONEST"
    assert result["ok"] is True


def test_every_derived_proof_has_hashed_evidence() -> None:
    result = evaluate(ROOT)
    for proof in result["proofs"]:
        assert proof["descriptor"].startswith(f"DERIVED:{proof['id']}:")
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
    assert result["technical_done"] < 775


def test_gate_is_fail_closed_when_source_hash_is_tampered(tmp_path: Path) -> None:
    source = ROOT / "docs/PRE_RUN_775_SOURCE_LOSS_CLOSURE.md"
    status = ROOT / "docs/PRE_RUN_775_CANONICAL_STATUS.json"
    (tmp_path / "docs").mkdir(parents=True)
    (tmp_path / "docs/PRE_RUN_775_SOURCE_LOSS_CLOSURE.md").write_text(
        source.read_text(encoding="utf-8") + "\nTAMPER\n", encoding="utf-8"
    )
    (tmp_path / "docs/PRE_RUN_775_CANONICAL_STATUS.json").write_text(
        status.read_text(encoding="utf-8"), encoding="utf-8"
    )
    result = evaluate(tmp_path)
    assert result["ok"] is False
    assert result["source_contract_ok"] is False


def test_status_manifest_still_denies_literal_reconstruction() -> None:
    status = json.loads((ROOT / "docs/PRE_RUN_775_CANONICAL_STATUS.json").read_text(encoding="utf-8"))
    assert status["literal_source_unrecoverable"] is True
    assert status["exact_literal_reconstruction_claimed"] is False
