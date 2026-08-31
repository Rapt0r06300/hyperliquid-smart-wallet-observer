from __future__ import annotations

from copy import deepcopy

from hl_observer.economics.assumptions import hash_payload
from hl_observer.research.external_evidence_governance import (
    audit_reference_architecture_receipt,
    audit_social_novelty_receipt,
    build_reference_architecture_receipt,
    build_social_novelty_receipt,
    v21_reference_and_recirculation_receipts,
)


def test_reference_only_ne_devient_jamais_production_ready() -> None:
    receipt = build_reference_architecture_receipt(
        source_id="vendor/templates",
        source_url="https://example.test/vendor/templates",
        source_hash=hash_payload({"repo": "vendor/templates", "revision": "abc"}),
        explicitly_reference_only=True,
    )

    assert receipt["source_classification"] == "REFERENCE_ARCHITECTURE"
    assert receipt["source_production_ready"] is False
    assert receipt["local_pattern_status"] == "LOCAL_VALIDATION_REQUIRED"
    assert receipt["local_pattern_adoption_allowed"] is False
    assert audit_reference_architecture_receipt(receipt)["ready"] is True


def test_pattern_local_exige_tests_comportement_et_securite() -> None:
    common = {
        "source_id": "vendor/templates",
        "source_url": "https://example.test/vendor/templates",
        "source_hash": hash_payload({"repo": "vendor/templates"}),
        "explicitly_reference_only": True,
        "local_validation_refs": ("tests/test_local_pattern.py",),
    }

    incomplete = build_reference_architecture_receipt(
        **common,
        local_behavior_tests_pass=True,
        local_safety_tests_pass=False,
    )
    complete = build_reference_architecture_receipt(
        **common,
        local_behavior_tests_pass=True,
        local_safety_tests_pass=True,
    )

    assert incomplete["local_pattern_adoption_allowed"] is False
    assert complete["local_pattern_status"] == "VALIDATED_LOCAL_PATTERN"
    assert complete["local_pattern_adoption_allowed"] is True
    assert complete["source_production_ready"] is False


def test_post_ancien_et_deja_publie_est_recirculation_sans_autorite() -> None:
    target = {"post": "target", "published_at": "2026-08-30T02:37:05Z"}
    artifact = {"release": "2026-05-05T00:00:00Z"}
    prior = {"post": "prior", "published_at": "2026-06-17T00:00:00Z"}
    receipt = build_social_novelty_receipt(
        target_source_ref="x:target",
        target_source_hash=hash_payload(target),
        target_published_at=target["published_at"],
        underlying_artifact_ref="vendor:artifact",
        underlying_artifact_hash=hash_payload(artifact),
        underlying_artifact_released_at=artifact["release"],
        novelty_terms=("just", "new"),
        prior_matches=(
            {
                "source_ref": "x:prior",
                "source_hash": hash_payload(prior),
                "published_at": prior["published_at"],
                "substantially_identical": True,
            },
        ),
    )

    assert receipt["classification"] == "RECIRCULATED"
    assert receipt["novelty_authority"] == 0.0
    assert receipt["wording_is_novelty_authority"] is False
    assert audit_social_novelty_receipt(receipt)["ready"] is True


def test_recu_mutable_est_detecte() -> None:
    receipts = v21_reference_and_recirculation_receipts()
    reference = deepcopy(receipts["reference_architecture"])
    novelty = deepcopy(receipts["social_novelty"])
    reference["source_production_ready"] = True
    novelty["novelty_authority"] = 1.0

    assert audit_reference_architecture_receipt(reference)["ready"] is False
    assert audit_social_novelty_receipt(novelty)["ready"] is False


def test_recus_v21_concrets_classent_reference_et_recirculation() -> None:
    receipts = v21_reference_and_recirculation_receipts()

    assert receipts["reference_architecture"]["source_classification"] == (
        "REFERENCE_ARCHITECTURE"
    )
    assert receipts["reference_architecture"]["source_production_ready"] is False
    assert receipts["social_novelty"]["classification"] == "RECIRCULATED"
    assert receipts["social_novelty"]["earlier_identical_match_count"] == 1
