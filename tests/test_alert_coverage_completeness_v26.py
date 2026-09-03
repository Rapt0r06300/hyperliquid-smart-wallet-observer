from __future__ import annotations

import copy
from pathlib import Path

import pytest

from hl_observer.alerts.coverage import (
    build_source_coverage_receipt,
    load_source_coverage_universe,
)
from hl_observer.alerts.coverage_completeness import (
    CoverageCompletenessError,
    build_coverage_completeness_attestation,
)

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_PATH = ROOT / "config" / "alerts" / "source_coverage_universe.json"


def _coverage_receipt() -> dict:
    return build_source_coverage_receipt(
        load_source_coverage_universe(UNIVERSE_PATH),
        [],
        evaluated_at_ms=10_000,
    )


def _recall_evidence(receipt: dict) -> dict:
    return {
        "kind": "MEASURED_RECALL_PROXY",
        "universe_hash": receipt["universe_hash"],
        "measured_at_ms": 9_000,
        "valid_for_ms": 5_000,
        "method": "Frozen labelled event sample with causal observation cutoff",
        "sample_definition": "100 pre-registered public events",
        "relevant_events": 100,
        "detected_events": 83,
        "evidence_refs": ["dataset:events-v1", "report:recall-v1"],
    }


def test_allocation_a_cent_pourcent_ne_prouve_jamais_la_completude() -> None:
    receipt = _coverage_receipt()
    attestation = build_coverage_completeness_attestation(
        receipt,
        evaluated_at_ms=10_000,
        allocation_percent={
            "SEC_FILINGS": 20,
            "OFFICIAL_MACRO_RELEASES": 20,
            "SELECTED_PUBLIC_NEWS": 30,
            "MARKET_MICROSTRUCTURE": 30,
        },
    )

    assert attestation["allocation"]["total_percent"] == 100.0
    assert (
        attestation["allocation"]["semantics"]
        == "CONFIGURATION_ONLY_NOT_COMPLETENESS_EVIDENCE"
    )
    assert attestation["coverage_state"] == "COVERAGE_UNKNOWN"
    assert attestation["completeness_claimed"] is False
    assert attestation["empirical_evidence_available"] is False


def test_compteurs_declares_ne_deviennent_pas_une_preuve_mesuree() -> None:
    receipt = _coverage_receipt()
    attestation = build_coverage_completeness_attestation(
        receipt,
        evaluated_at_ms=10_000,
        allocation_percent={"SEC_FILINGS": 100},
        evidence=_recall_evidence(receipt),
    )

    assert attestation["coverage_state"] == "COVERAGE_UNKNOWN"
    assert attestation["empirical_evidence_available"] is False
    assert attestation["completeness_evidence"]["reported_recall"] == 0.83
    assert "COMPLETENESS_EVIDENCE_UNVERIFIED" in attestation["evidence_rejection_reasons"]
    assert attestation["completeness_evidence"]["universe_hash"] == receipt[
        "universe_hash"
    ]
    assert attestation["completeness_claimed"] is False
    assert len(attestation["attestation_hash"]) == 64


def test_hash_autoritatif_sans_artefact_verifie_ne_prouve_rien() -> None:
    receipt = _coverage_receipt()
    evidence = {
        "kind": "SOURCE_UNIVERSE_RECEIPT",
        "universe_hash": receipt["universe_hash"],
        "measured_at_ms": 9_000,
        "valid_for_ms": 5_000,
        "method": "Official endpoint inventory receipt",
        "authority": "US-SEC",
        "scope": "SEC EDGAR public endpoint inventory",
        "authoritative_receipt_hash": "a" * 64,
        "declared_sources": 10,
        "observed_sources": 9,
        "evidence_refs": ["receipt:sec-endpoints-v1"],
    }

    attestation = build_coverage_completeness_attestation(
        receipt, evaluated_at_ms=10_000, evidence=evidence
    )

    assert attestation["coverage_state"] == "COVERAGE_UNKNOWN"
    assert attestation["empirical_evidence_available"] is False
    assert attestation["completeness_evidence"]["reported_observed_ratio"] == 0.9
    assert "COMPLETENESS_EVIDENCE_UNVERIFIED" in attestation["evidence_rejection_reasons"]
    assert attestation["completeness_claimed"] is False


def test_preuve_perimee_retombe_explicitement_sur_coverage_unknown() -> None:
    receipt = _coverage_receipt()
    evidence = _recall_evidence(receipt)
    evidence["measured_at_ms"] = 1_000
    evidence["valid_for_ms"] = 2_000

    attestation = build_coverage_completeness_attestation(
        receipt, evaluated_at_ms=10_000, evidence=evidence
    )

    assert attestation["coverage_state"] == "COVERAGE_UNKNOWN"
    assert attestation["empirical_evidence_available"] is False
    assert attestation["evidence_rejection_reasons"] == [
        "COMPLETENESS_EVIDENCE_STALE", "COMPLETENESS_EVIDENCE_UNVERIFIED"
    ]


def test_preuve_mal_liee_ou_recu_source_modifie_sont_refuses() -> None:
    receipt = _coverage_receipt()
    evidence = _recall_evidence(receipt)
    evidence["universe_hash"] = "f" * 64
    with pytest.raises(
        CoverageCompletenessError,
        match="COMPLETENESS_UNIVERSE_BINDING_MISMATCH",
    ):
        build_coverage_completeness_attestation(
            receipt, evaluated_at_ms=10_000, evidence=evidence
        )

    tampered = copy.deepcopy(receipt)
    tampered["workflow_id"] = "tampered-workflow"
    with pytest.raises(
        CoverageCompletenessError,
        match="SOURCE_COVERAGE_RECEIPT_HASH_INVALID",
    ):
        build_coverage_completeness_attestation(tampered, evaluated_at_ms=10_000)


def test_preuve_future_compteurs_impossibles_et_classe_inconnue_sont_refuses() -> None:
    receipt = _coverage_receipt()
    future = _recall_evidence(receipt)
    future["measured_at_ms"] = 10_001
    with pytest.raises(CoverageCompletenessError, match="EVIDENCE_FROM_FUTURE"):
        build_coverage_completeness_attestation(
            receipt, evaluated_at_ms=10_000, evidence=future
        )

    impossible = _recall_evidence(receipt)
    impossible["detected_events"] = 101
    with pytest.raises(CoverageCompletenessError, match="DETECTED_EXCEEDS_RELEVANT"):
        build_coverage_completeness_attestation(
            receipt, evaluated_at_ms=10_000, evidence=impossible
        )

    with pytest.raises(CoverageCompletenessError, match="ALLOCATION_CLASS_UNKNOWN"):
        build_coverage_completeness_attestation(
            receipt,
            evaluated_at_ms=10_000,
            allocation_percent={"UNDECLARED_CLASS": 100},
        )


def test_attestation_est_deterministe_et_sans_capacite_execution() -> None:
    receipt = _coverage_receipt()
    first = build_coverage_completeness_attestation(
        receipt, evaluated_at_ms=10_000, evidence=_recall_evidence(receipt)
    )
    second = build_coverage_completeness_attestation(
        receipt, evaluated_at_ms=10_000, evidence=_recall_evidence(receipt)
    )

    assert first == second
    assert first["paper_read_only"] is True
    assert first["real_execution"] is False
    assert first["execution_capability"] == "NONE"


@pytest.mark.parametrize("value", [83.9, "83", True, float("nan"), float("inf")])
def test_compteurs_non_entiers_sont_refuses_sans_troncature(value: object) -> None:
    receipt = _coverage_receipt()
    evidence = _recall_evidence(receipt)
    evidence["detected_events"] = value
    with pytest.raises(CoverageCompletenessError, match="INTEGER_INVALID"):
        build_coverage_completeness_attestation(
            receipt, evaluated_at_ms=10_000, evidence=evidence
        )


def test_attestation_ne_peut_pas_utiliser_un_recu_source_du_futur() -> None:
    with pytest.raises(CoverageCompletenessError, match="SOURCE_COVERAGE_RECEIPT_FROM_FUTURE"):
        build_coverage_completeness_attestation(
            _coverage_receipt(), evaluated_at_ms=9_999
        )
