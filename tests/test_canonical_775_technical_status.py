from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from hl_observer.ops.canonical_775_guard import IN_PROGRESS_TECHNICAL_775_SOURCE_LOSS_HONEST, validate_manifest
from hl_observer.ops.pre_run_guard_321_775 import evaluate

ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "docs/PRE_RUN_775_CANONICAL_STATUS.json"


def _manifest() -> dict[str, object]:
    return json.loads(STATUS_PATH.read_text(encoding="utf-8"))


def test_canonical_status_is_honest_in_progress_545() -> None:
    manifest = _manifest(); result = validate_manifest(manifest)
    assert result["ok"] is True, result["issues"]
    assert result["status"] == IN_PROGRESS_TECHNICAL_775_SOURCE_LOSS_HONEST
    assert result["technical_completion_claimed"] is False and result["technical_done"] == 545
    assert manifest["literal_source_unrecoverable"] is True and manifest["exact_literal_reconstruction_claimed"] is False


def test_canonical_status_matches_specific_executable_progress_gate() -> None:
    manifest = _manifest(); gate = evaluate(ROOT)
    assert gate["ok"] is True and gate["complete"] is False
    assert gate["technical_done"] == manifest["technical_completion_done"] == 545
    assert gate["derived_proofs_done"] == manifest["derived_technical_controls"]["done"] == 225
    assert gate["base_requirements_done"] == manifest["derived_technical_controls"]["base_requirements_done"] == 45
    assert manifest["derived_technical_controls"]["next_unverified_id"] == 546


def test_progress_rejects_fake_literal_reconstruction() -> None:
    manifest = _manifest(); manifest["exact_literal_reconstruction_claimed"] = True; result = validate_manifest(manifest)
    assert result["ok"] is False
    assert "SOURCE_LOSS_FORBIDS_LITERAL_RECONSTRUCTION_CLAIM" in result["issues"]


def test_progress_rejects_false_775_claim() -> None:
    manifest = _manifest(); manifest["technical_completion_done"] = 775; result = validate_manifest(manifest)
    assert result["ok"] is False
    assert "TECHNICAL_PROGRESS_DONE_RANGE_INVALID" in result["issues"]


def test_progress_rejects_derived_counter_inconsistency() -> None:
    manifest = _manifest(); derived = deepcopy(manifest["derived_technical_controls"]); derived["done"] = 455; manifest["derived_technical_controls"] = derived; result = validate_manifest(manifest)
    assert result["ok"] is False
    assert "TECHNICAL_PROGRESS_DERIVED_DONE_MISMATCH" in result["issues"]


def test_superseded_generic_file_completion_is_recorded_as_withdrawn() -> None:
    retired = _manifest()["superseded_false_completion"]
    assert retired["status"] == "WITHDRAWN" and retired["previous_claim"] == 775
