from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from hl_observer.ops.canonical_775_guard import (
    DONE_TECHNICAL_775_SOURCE_LOSS_HONEST,
    validate_manifest,
)
from hl_observer.ops.pre_run_guard_321_775 import evaluate

ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "docs/PRE_RUN_775_CANONICAL_STATUS.json"


def _manifest() -> dict[str, object]:
    return json.loads(STATUS_PATH.read_text(encoding="utf-8"))


def test_canonical_status_is_775_technical_done_and_honest_about_source_loss() -> None:
    manifest = _manifest()
    result = validate_manifest(manifest)
    assert result["ok"] is True, result["issues"]
    assert result["status"] == DONE_TECHNICAL_775_SOURCE_LOSS_HONEST
    assert result["technical_completion_claimed"] is True
    assert result["technical_done"] == 775
    assert manifest["literal_source_unrecoverable"] is True
    assert manifest["exact_literal_reconstruction_claimed"] is False


def test_canonical_status_matches_executable_derived_gate() -> None:
    manifest = _manifest()
    gate = evaluate(ROOT)
    assert gate["ok"] is True
    assert gate["technical_done"] == manifest["technical_completion_done"] == 775
    assert gate["derived_proofs_done"] == manifest["derived_technical_controls"]["count"] == 455
    assert gate["base_requirements_done"] == manifest["derived_technical_controls"]["base_requirements"] == 91


def test_technical_done_rejects_fake_literal_reconstruction() -> None:
    manifest = _manifest()
    manifest["exact_literal_reconstruction_claimed"] = True
    result = validate_manifest(manifest)
    assert result["ok"] is False
    assert "SOURCE_LOSS_FORBIDS_LITERAL_RECONSTRUCTION_CLAIM" in result["issues"]


def test_technical_done_rejects_any_missing_control() -> None:
    manifest = _manifest()
    manifest["technical_completion_done"] = 774
    result = validate_manifest(manifest)
    assert result["ok"] is False
    assert "TECHNICAL_DONE_REQUIRES_DONE_775" in result["issues"]


def test_technical_done_rejects_relabeling_derived_controls_as_historical() -> None:
    manifest = _manifest()
    derived = deepcopy(manifest["derived_technical_controls"])
    derived["historical_literal"] = True
    manifest["derived_technical_controls"] = derived
    result = validate_manifest(manifest)
    assert result["ok"] is False
    assert "TECHNICAL_DONE_DERIVED_MISMATCH:historical_literal" in result["issues"]


def test_technical_done_rejects_wrong_initial_ci_evidence() -> None:
    manifest = _manifest()
    first_run = deepcopy(manifest["technical_completion_initial_green_run"])
    first_run["conclusion"] = "failure"
    manifest["technical_completion_initial_green_run"] = first_run
    result = validate_manifest(manifest)
    assert result["ok"] is False
    assert "TECHNICAL_DONE_INITIAL_RUN_NOT_GREEN" in result["issues"]
