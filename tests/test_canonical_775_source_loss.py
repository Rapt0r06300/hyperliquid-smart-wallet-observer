from __future__ import annotations

import hashlib
import json
from pathlib import Path

from hl_observer.ops.canonical_775_guard import IN_PROGRESS_TECHNICAL_775_SOURCE_LOSS_HONEST, KNOWN_CANONICAL_ANCHORS, REQUIRED_SOURCE_SEARCHES, ROADMAP_ID, ROADMAP_TOTAL, THEMATIC_REQUIREMENTS_PATH, validate_manifest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docs/PRE_RUN_775_CANONICAL_STATUS.json"
THEMATIC_PATH = ROOT / THEMATIC_REQUIREMENTS_PATH


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_source_loss_terminal_est_honnete_et_progression_technique_non_faussee() -> None:
    manifest = _manifest(); result = validate_manifest(manifest)
    assert result["ok"] is True and result["status"] == IN_PROGRESS_TECHNICAL_775_SOURCE_LOSS_HONEST
    assert result["terminal_recovery"] is True and result["technical_completion_claimed"] is False
    assert result["technical_done"] == 545
    assert manifest["blocking"] is False and manifest["next_unrecovered_literal"] is None
    assert manifest["literal_source_unrecoverable"] is True and manifest["exact_literal_reconstruction_claimed"] is False
    assert manifest["technical_completion_total"] == ROADMAP_TOTAL and manifest["technical_completion_done"] == 545
    assert set(manifest["source_searches_completed"]) >= REQUIRED_SOURCE_SEARCHES


def test_source_loss_conserve_toutes_les_ancres_exactes_connues() -> None:
    manifest = _manifest()
    for number, label in KNOWN_CANONICAL_ANCHORS.items():
        assert manifest["anchors"][str(number)] == label
        assert manifest["recovered_literal_labels"][str(number)] == label
    assert manifest["recovered_literal_count"] == len(KNOWN_CANONICAL_ANCHORS)


def test_exigences_thematiques_sont_scellees_par_sha256() -> None:
    manifest = _manifest(); payload = THEMATIC_PATH.read_bytes(); digest = hashlib.sha256(payload).hexdigest()
    assert manifest["thematic_requirements_path"] == THEMATIC_REQUIREMENTS_PATH and digest == manifest["thematic_requirements_sha256"]
    text = payload.decode("utf-8")
    for required in ("Copy-Vault", "Lead-Lag", "Cross-Venue Dislocation", "Anti-overfit", "MAX DATA", "Self-hosted runner", "Windows portable", "Observabilité", "GO_SELF_HOSTED = TRUE"):
        assert required in text


def test_source_loss_ne_peut_pas_devenir_un_faux_done() -> None:
    manifest = _manifest(); manifest["status"] = "DONE"; result = validate_manifest(manifest)
    assert result["ok"] is False
    assert "DONE_REQUIRES_775_LITERAL_LABELS" in result["issues"] and "DONE_REQUIRES_775_EXECUTABLE_PROOFS" in result["issues"]


def test_source_loss_refuse_un_faux_jeu_de_labels_ou_preuves() -> None:
    manifest = _manifest(); manifest["labels"] = ["inventé"] * ROADMAP_TOTAL; manifest["proofs"] = {str(i): f"preuve-{i}" for i in range(1, ROADMAP_TOTAL + 1)}; result = validate_manifest(manifest)
    assert result["ok"] is False
    assert "SOURCE_LOSS_FORBIDS_CANONICAL_LABEL_SET" in result["issues"] and "SOURCE_LOSS_FORBIDS_775_LITERAL_PROOF_CLAIM" in result["issues"]


def test_identite_et_total_canoniques_restent_immuables() -> None:
    manifest = _manifest(); assert manifest["roadmap_id"] == ROADMAP_ID; assert manifest["total"] == ROADMAP_TOTAL
