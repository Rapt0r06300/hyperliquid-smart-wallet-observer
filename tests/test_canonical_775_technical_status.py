from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from hl_observer.ops.canonical_775_guard import (
    DONE_TECHNICAL_775_SOURCE_LOSS_HONEST,
    IN_PROGRESS_TECHNICAL_775_SOURCE_LOSS_HONEST,
    validate_manifest,
)
from hl_observer.ops.pre_run_guard_321_775 import evaluate

ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "docs/PRE_RUN_775_CANONICAL_STATUS.json"


def _manifest() -> dict:
    return json.loads(STATUS_PATH.read_text(encoding="utf-8"))


def test_canonical_manifest_is_honest_during_or_after_finalization() -> None:
    manifest = _manifest(); result = validate_manifest(manifest)
    assert result["ok"] is True, result["issues"]
    assert result["status"] in {
        IN_PROGRESS_TECHNICAL_775_SOURCE_LOSS_HONEST,
        DONE_TECHNICAL_775_SOURCE_LOSS_HONEST,
    }
    assert manifest["literal_source_unrecoverable"] is True
    assert manifest["exact_literal_reconstruction_claimed"] is False
    if result["status"] == DONE_TECHNICAL_775_SOURCE_LOSS_HONEST:
        assert result["technical_completion_claimed"] is True
        assert result["technical_done"] == 775
    else:
        # Transitional state is allowed only while the newly implemented 775 gate
        # is being proven by CI; the workflow itself refuses to call it final.
        assert result["technical_completion_claimed"] is False
        assert 320 <= result["technical_done"] < 775


def test_specific_executable_gate_reaches_all_775_before_manifest_finalization() -> None:
    manifest = _manifest(); gate = evaluate(ROOT)
    assert gate["ok"] is True, gate
    assert gate["complete"] is True, gate
    assert gate["technical_done"] == 775
    assert gate["derived_proofs_done"] == 455
    assert gate["base_requirements_done"] == 91
    assert gate["next_derived_id"] is None
    assert gate["remaining_546_775"] == {
        "ok": True,
        "requirements_done": 46,
        "requirements_total": 46,
        "facets_done": 230,
        "facets_total": 230,
    }
    if manifest.get("technical_completion_claimed") is True:
        assert manifest["technical_completion_done"] == 775
        assert manifest["derived_technical_controls"]["done"] == 455


def test_source_loss_still_rejects_fake_literal_reconstruction() -> None:
    manifest = _manifest(); manifest["exact_literal_reconstruction_claimed"] = True
    result = validate_manifest(manifest)
    assert result["ok"] is False
    assert "SOURCE_LOSS_FORBIDS_LITERAL_RECONSTRUCTION_CLAIM" in result["issues"]


def test_in_progress_status_cannot_claim_775() -> None:
    manifest = _manifest()
    manifest["status"] = IN_PROGRESS_TECHNICAL_775_SOURCE_LOSS_HONEST
    manifest["technical_completion_claimed"] = False
    manifest["technical_completion_done"] = 775
    result = validate_manifest(manifest)
    assert result["ok"] is False
    assert "TECHNICAL_PROGRESS_DONE_RANGE_INVALID" in result["issues"]


def test_done_status_requires_all_455_derived_controls() -> None:
    manifest = _manifest()
    manifest["status"] = DONE_TECHNICAL_775_SOURCE_LOSS_HONEST
    manifest["technical_completion_claimed"] = True
    manifest["technical_completion_done"] = 775
    derived = deepcopy(manifest["derived_technical_controls"])
    derived["done"] = 454
    manifest["derived_technical_controls"] = derived
    result = validate_manifest(manifest)
    assert result["ok"] is False
    assert "TECHNICAL_DONE_DERIVED_MISMATCH:done" in result["issues"]


def test_superseded_generic_file_completion_is_recorded_as_withdrawn() -> None:
    retired = _manifest()["superseded_false_completion"]
    assert retired["status"] == "WITHDRAWN" and retired["previous_claim"] == 775
