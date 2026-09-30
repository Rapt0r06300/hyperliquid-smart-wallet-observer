from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from hl_observer.alerts.coverage import (
    SOURCE_CLASSES,
    SourceCoverageError,
    build_source_coverage_receipt,
    load_source_coverage_universe,
    validate_source_coverage_universe,
)
from tools.check_source_coverage import main

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_PATH = ROOT / "config" / "alerts" / "source_coverage_universe.json"


def _payload() -> dict:
    return json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))


def _one_source_universe() -> dict:
    payload = _payload()
    payload["coverage_classes"] = [
        {
            "class_id": "MARKET_MICROSTRUCTURE",
            "desired_sources": [
                {
                    "source_id": "hyperliquid-info-l2book",
                    "authority": "HYPERLIQUID",
                    "required": True,
                    "entitlement": "PUBLIC_ZERO_EURO",
                    "license_class": "PUBLIC_API_TERMS_REVIEW_REQUIRED",
                    "latency_slo_ms": 2_000,
                    "freshness_slo_ms": 4_000,
                    "validation_slo_ms": 86_400_000,
                }
            ],
            "known_exclusions": ["Private queue state is unavailable."],
        }
    ]
    return payload


def _healthy_observation() -> dict:
    return {
        "source_id": "hyperliquid-info-l2book",
        "connection_state": "CONNECTED",
        "source_status": "HEALTHY",
        "entitlement": "PUBLIC_ZERO_EURO",
        "license_class": "PUBLIC_API_TERMS_REVIEW_REQUIRED",
        "latency_ms": 125.5,
        "last_successful_refresh_ms": 9_500,
        "last_validated_at_ms": 9_000,
        "validation_evidence_refs": ["canary:l2book:sha256-deadbeef"],
    }


def test_univers_configure_couvre_explicitement_les_sept_classes() -> None:
    universe = load_source_coverage_universe(UNIVERSE_PATH)

    assert {item["class_id"] for item in universe["coverage_classes"]} == set(
        SOURCE_CLASSES
    )
    assert all(item["desired_sources"] for item in universe["coverage_classes"])
    assert all("known_exclusions" in item for item in universe["coverage_classes"])
    assert len(universe["universe_hash"]) == 64
    assert universe["paper_read_only"] is True
    assert universe["real_execution"] is False


def test_absence_de_preuve_devient_gap_et_jamais_couverture_implicite() -> None:
    receipt = build_source_coverage_receipt(
        load_source_coverage_universe(UNIVERSE_PATH),
        [],
        evaluated_at_ms=10_000,
    )

    assert receipt["counts"]["classes"] == 7
    assert receipt["counts"]["actually_connected_sources"] == 0
    assert receipt["counts"]["blocking_gaps"] > 0
    assert receipt["operational_state"] == "BLOCKED"
    assert receipt["completeness_state"] == "COVERAGE_UNKNOWN"
    assert receipt["completeness_claimed"] is False
    assert receipt["allocation_is_not_completeness_evidence"] is True
    assert receipt["execution_capability"] == "NONE"
    assert all(
        item["actually_connected_sources"] == []
        for item in receipt["coverage_classes"]
    )
    assert {gap["code"] for gap in receipt["gap_ledger"]} >= {
        "SOURCE_NOT_CONNECTED",
        "SOURCE_NOT_HEALTHY",
        "LATENCY_UNMEASURED",
        "FRESHNESS_UNMEASURED",
        "LAST_VALIDATION_MISSING",
        "VALIDATION_EVIDENCE_MISSING",
        "KNOWN_EXCLUSION",
    }


def test_source_connectee_enregistre_statut_droits_latence_fraicheur_validation() -> None:
    receipt = build_source_coverage_receipt(
        _one_source_universe(),
        [_healthy_observation()],
        evaluated_at_ms=10_000,
    )
    class_receipt = receipt["coverage_classes"][0]
    source = class_receipt["source_status"][0]

    assert class_receipt["desired_sources"] == ["hyperliquid-info-l2book"]
    assert class_receipt["actually_connected_sources"] == [
        "hyperliquid-info-l2book"
    ]
    assert class_receipt["operational_state"] == "READY"
    assert class_receipt["completeness_state"] == "COVERAGE_UNKNOWN"
    assert source == {
        "source_id": "hyperliquid-info-l2book",
        "authority": "HYPERLIQUID",
        "required": True,
        "connection_state": "CONNECTED",
        "source_status": "HEALTHY",
        "entitlement": "PUBLIC_ZERO_EURO",
        "license_class": "PUBLIC_API_TERMS_REVIEW_REQUIRED",
        "latency_ms": 125.5,
        "latency_slo_ms": 2_000,
        "last_successful_refresh_ms": 9_500,
        "refresh_age_ms": 500,
        "freshness_slo_ms": 4_000,
        "last_validated_at_ms": 9_000,
        "validation_age_ms": 1_000,
        "validation_slo_ms": 86_400_000,
        "validation_evidence_refs": ["canary:l2book:sha256-deadbeef"],
    }
    assert receipt["counts"]["blocking_gaps"] == 0
    assert {gap["code"] for gap in receipt["gap_ledger"]} == {
        "KNOWN_EXCLUSION"
    }


def test_source_stale_ou_non_validee_ne_peut_pas_etre_prete() -> None:
    observation = _healthy_observation()
    observation["source_status"] = "STALE"
    observation["latency_ms"] = 2_001
    observation["last_successful_refresh_ms"] = 1_000
    observation["last_validated_at_ms"] = None
    observation["validation_evidence_refs"] = []

    receipt = build_source_coverage_receipt(
        _one_source_universe(), [observation], evaluated_at_ms=10_000
    )
    codes = {gap["code"] for gap in receipt["gap_ledger"]}

    assert receipt["operational_state"] == "BLOCKED"
    assert codes >= {
        "SOURCE_NOT_HEALTHY",
        "LATENCY_SLO_BREACH",
        "FRESHNESS_SLO_BREACH",
        "LAST_VALIDATION_MISSING",
        "VALIDATION_EVIDENCE_MISSING",
    }


def test_source_observee_hors_univers_et_doublons_sont_refuses() -> None:
    observation = _healthy_observation()
    observation["source_id"] = "surprise-wire"
    with pytest.raises(SourceCoverageError, match="OBSERVED_SOURCE_UNDECLARED"):
        build_source_coverage_receipt(
            _one_source_universe(), [observation], evaluated_at_ms=10_000
        )

    payload = _one_source_universe()
    payload["coverage_classes"][0]["desired_sources"].append(
        copy.deepcopy(payload["coverage_classes"][0]["desired_sources"][0])
    )
    with pytest.raises(SourceCoverageError, match="DESIRED_SOURCE_DUPLICATE"):
        validate_source_coverage_universe(payload)


def test_hash_est_deterministe_malgre_ordre_des_observations() -> None:
    payload = _one_source_universe()
    second = copy.deepcopy(payload["coverage_classes"][0]["desired_sources"][0])
    second["source_id"] = "hyperliquid-info-allmids"
    payload["coverage_classes"][0]["desired_sources"].append(second)
    first_observation = _healthy_observation()
    second_observation = copy.deepcopy(first_observation)
    second_observation["source_id"] = "hyperliquid-info-allmids"

    first = build_source_coverage_receipt(
        payload,
        [first_observation, second_observation],
        evaluated_at_ms=10_000,
    )
    second_receipt = build_source_coverage_receipt(
        payload,
        [second_observation, first_observation],
        evaluated_at_ms=10_000,
    )
    assert first == second_receipt
    assert len(first["receipt_hash"]) == 64


def test_mode_execution_est_refuse_et_outil_expose_coverage_inconnue(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _payload()
    payload["real_execution"] = True
    with pytest.raises(SourceCoverageError, match="COVERAGE_REAL_EXECUTION_FORBIDDEN"):
        validate_source_coverage_universe(payload)

    assert main(["--universe", str(UNIVERSE_PATH), "--evaluated-at-ms", "10000"]) == 0
    output = capsys.readouterr().out
    assert "SOURCE_COVERAGE_OK" in output
    assert "classes=7" in output
    assert "connected=0" in output
    assert "completeness=COVERAGE_UNKNOWN" in output
