from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from hl_observer.alerts.replacement_parity import (
    PARITY_DIMENSIONS,
    ReplacementParityError,
    load_replacement_assessment,
    validate_replacement_assessment,
)
from tools.check_replacement_parity import main

ROOT = Path(__file__).resolve().parents[1]
ASSESSMENT_PATH = ROOT / "config" / "alerts" / "roh_maxdeg0_vs_bloomberg.json"


def _payload() -> dict:
    return json.loads(ASSESSMENT_PATH.read_text(encoding="utf-8"))


def test_configuration_roh_maxdeg0_reste_partielle_et_decomposee() -> None:
    assessment = load_replacement_assessment(ASSESSMENT_PATH)

    assert assessment["verdict"] == "PARTIAL_SUBSTITUTE"
    assert set(assessment["dimensions"]) == set(PARITY_DIMENSIONS)
    assert assessment["dimensions"]["communications_network"]["state"] == "ABSENT"
    assert assessment["dimensions"]["execution_capabilities"]["state"] == "ABSENT"
    assert len(assessment["assessment_hash"]) == 64
    assert assessment["paper_read_only"] is True
    assert assessment["real_execution"] is False


def test_dimension_manquante_refuse_toute_affirmation_globale() -> None:
    payload = _payload()
    payload["dimensions"].pop("reliability_sla")

    with pytest.raises(
        ReplacementParityError,
        match="ASSESSMENT_DIMENSIONS_INCOMPLETE",
    ):
        validate_replacement_assessment(payload)


def test_parite_prouvee_est_refusee_des_qu_un_gap_reste() -> None:
    payload = _payload()
    payload["verdict"] = "PARITY_PROVEN"

    with pytest.raises(
        ReplacementParityError,
        match="PARITY_PROVEN_WITH_CAPABILITY_GAPS",
    ):
        validate_replacement_assessment(payload)


def test_dimension_partielle_sans_preuve_est_refusee() -> None:
    payload = _payload()
    payload["dimensions"]["analytics"]["evidence_refs"] = []

    with pytest.raises(
        ReplacementParityError,
        match="DIMENSION_EVIDENCE_MISSING:analytics",
    ):
        validate_replacement_assessment(payload)


def test_hash_fourni_ne_peut_pas_masquer_une_mutation() -> None:
    normalized = validate_replacement_assessment(_payload())
    tampered = copy.deepcopy(normalized)
    tampered["scope"] = "Unbounded replacement claim"

    with pytest.raises(ReplacementParityError, match="ASSESSMENT_HASH_MISMATCH"):
        validate_replacement_assessment(tampered)


def test_outil_valide_toutes_les_matrices_configurees(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(ASSESSMENT_PATH.parent)]) == 0
    output = capsys.readouterr().out
    assert "REPLACEMENT_PARITY_OK" in output
    assert "verdict=PARTIAL_SUBSTITUTE" in output
