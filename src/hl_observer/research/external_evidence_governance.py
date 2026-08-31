"""Typed governance receipts for external reference code and social novelty."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from hl_observer.economics.assumptions import hash_payload

REFERENCE_RECEIPT_SCHEMA = "hypersmart.external_reference_architecture.v1"
SOCIAL_NOVELTY_SCHEMA = "hypersmart.social_novelty_receipt.v1"


class ReferenceArchitectureClass(StrEnum):
    REFERENCE_ARCHITECTURE = "REFERENCE_ARCHITECTURE"
    EXTERNAL_IMPLEMENTATION_UNVERIFIED = "EXTERNAL_IMPLEMENTATION_UNVERIFIED"


class LocalPatternStatus(StrEnum):
    LOCAL_VALIDATION_REQUIRED = "LOCAL_VALIDATION_REQUIRED"
    VALIDATED_LOCAL_PATTERN = "VALIDATED_LOCAL_PATTERN"


class SocialNoveltyClass(StrEnum):
    NOVEL_ARTIFACT = "NOVEL_ARTIFACT"
    NOT_NEW_ARTIFACT = "NOT_NEW_ARTIFACT"
    RECIRCULATED = "RECIRCULATED"
    UNMEASURABLE_NOVELTY = "UNMEASURABLE_NOVELTY"


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _with_receipt_hash(body: Mapping[str, Any]) -> dict[str, Any]:
    return {**body, "receipt_sha256": hash_payload(dict(body))}


def build_reference_architecture_receipt(
    *,
    source_id: str,
    source_url: str,
    source_hash: str,
    explicitly_reference_only: bool,
    local_validation_refs: Iterable[str] = (),
    local_behavior_tests_pass: bool = False,
    local_safety_tests_pass: bool = False,
) -> dict[str, Any]:
    """Classify source architecture separately from a locally validated pattern."""

    failures: list[str] = []
    if not source_id.strip() or not source_url.strip():
        failures.append("SOURCE_IDENTITY_MISSING")
    if not _is_sha256(source_hash):
        failures.append("SOURCE_HASH_INVALID")
    refs = sorted({str(ref).strip() for ref in local_validation_refs if str(ref).strip()})
    local_validated = bool(
        refs and local_behavior_tests_pass and local_safety_tests_pass and not failures
    )
    source_class = (
        ReferenceArchitectureClass.REFERENCE_ARCHITECTURE
        if explicitly_reference_only
        else ReferenceArchitectureClass.EXTERNAL_IMPLEMENTATION_UNVERIFIED
    )
    body = {
        "schema_version": REFERENCE_RECEIPT_SCHEMA,
        "source_id": source_id.strip(),
        "source_url": source_url.strip(),
        "source_hash": source_hash,
        "source_classification": source_class.value,
        "source_production_ready": False,
        "local_pattern_status": (
            LocalPatternStatus.VALIDATED_LOCAL_PATTERN.value
            if local_validated
            else LocalPatternStatus.LOCAL_VALIDATION_REQUIRED.value
        ),
        "local_pattern_adoption_allowed": local_validated,
        "local_validation_refs": refs,
        "local_behavior_tests_pass": bool(local_behavior_tests_pass),
        "local_safety_tests_pass": bool(local_safety_tests_pass),
        "failures": failures,
    }
    return _with_receipt_hash(body)


def audit_reference_architecture_receipt(receipt: object) -> dict[str, Any]:
    issues: list[str] = []
    if not isinstance(receipt, Mapping):
        return {"ready": False, "issues": ["REFERENCE_RECEIPT_MISSING"]}
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("schema_version") != REFERENCE_RECEIPT_SCHEMA:
        issues.append("REFERENCE_RECEIPT_SCHEMA_INVALID")
    if hash_payload(body) != receipt.get("receipt_sha256"):
        issues.append("REFERENCE_RECEIPT_HASH_MISMATCH")
    if receipt.get("source_production_ready") is not False:
        issues.append("EXTERNAL_SOURCE_MUST_NOT_BE_PRODUCTION_READY")
    classification = receipt.get("source_classification")
    if classification not in {item.value for item in ReferenceArchitectureClass}:
        issues.append("REFERENCE_CLASSIFICATION_INVALID")
    refs = receipt.get("local_validation_refs")
    validated = receipt.get("local_pattern_status") == LocalPatternStatus.VALIDATED_LOCAL_PATTERN
    expected_adoption = bool(
        validated
        and isinstance(refs, list)
        and refs
        and receipt.get("local_behavior_tests_pass") is True
        and receipt.get("local_safety_tests_pass") is True
        and not receipt.get("failures")
    )
    if receipt.get("local_pattern_adoption_allowed") is not expected_adoption:
        issues.append("LOCAL_PATTERN_ADOPTION_GATE_MISMATCH")
    return {
        "ready": not issues,
        "issues": issues,
        "source_classification": classification,
        "local_pattern_adoption_allowed": expected_adoption,
    }


def build_social_novelty_receipt(
    *,
    target_source_ref: str,
    target_source_hash: str,
    target_published_at: str | datetime,
    underlying_artifact_ref: str,
    underlying_artifact_hash: str,
    underlying_artifact_released_at: str | datetime,
    novelty_terms: Iterable[str] = (),
    prior_matches: Iterable[Mapping[str, Any]] = (),
    novelty_window_days: int = 7,
) -> dict[str, Any]:
    """Decide novelty from artifact chronology, never from promotional wording."""

    issues: list[str] = []
    target_at = _parse_timestamp(target_published_at)
    artifact_at = _parse_timestamp(underlying_artifact_released_at)
    if not target_source_ref.strip() or not underlying_artifact_ref.strip():
        issues.append("SOURCE_REFERENCE_MISSING")
    if not _is_sha256(target_source_hash):
        issues.append("TARGET_SOURCE_HASH_INVALID")
    if not _is_sha256(underlying_artifact_hash):
        issues.append("UNDERLYING_ARTIFACT_HASH_INVALID")
    if target_at is None:
        issues.append("TARGET_TIMESTAMP_INVALID")
    if artifact_at is None:
        issues.append("ARTIFACT_TIMESTAMP_INVALID")

    normalized_prior: list[dict[str, Any]] = []
    for index, prior in enumerate(prior_matches):
        ref = str(prior.get("source_ref") or "").strip()
        source_hash = str(prior.get("source_hash") or "")
        published_at = _parse_timestamp(prior.get("published_at"))
        substantially_identical = prior.get("substantially_identical") is True
        if not ref or not _is_sha256(source_hash) or published_at is None:
            issues.append(f"PRIOR_MATCH_INVALID:{index}")
            continue
        normalized_prior.append(
            {
                "source_ref": ref,
                "source_hash": source_hash,
                "published_at": published_at.isoformat(),
                "substantially_identical": substantially_identical,
            }
        )
    normalized_prior.sort(key=lambda row: (row["published_at"], row["source_ref"]))

    earlier_matches = [
        row
        for row in normalized_prior
        if target_at is not None
        and _parse_timestamp(row["published_at"]) < target_at
        and row["substantially_identical"] is True
    ]
    if issues or target_at is None or artifact_at is None:
        classification = SocialNoveltyClass.UNMEASURABLE_NOVELTY
        novelty_authority: float | None = None
    elif earlier_matches:
        classification = SocialNoveltyClass.RECIRCULATED
        novelty_authority = 0.0
    elif artifact_at < target_at - timedelta(days=max(0, int(novelty_window_days))):
        classification = SocialNoveltyClass.NOT_NEW_ARTIFACT
        novelty_authority = 0.0
    else:
        classification = SocialNoveltyClass.NOVEL_ARTIFACT
        novelty_authority = 1.0

    body = {
        "schema_version": SOCIAL_NOVELTY_SCHEMA,
        "target_source_ref": target_source_ref.strip(),
        "target_source_hash": target_source_hash,
        "target_published_at": target_at.isoformat() if target_at else None,
        "underlying_artifact_ref": underlying_artifact_ref.strip(),
        "underlying_artifact_hash": underlying_artifact_hash,
        "underlying_artifact_released_at": artifact_at.isoformat() if artifact_at else None,
        "novelty_terms": sorted(
            {str(term).strip().lower() for term in novelty_terms if str(term).strip()}
        ),
        "prior_matches": normalized_prior,
        "earlier_identical_match_count": len(earlier_matches),
        "novelty_window_days": max(0, int(novelty_window_days)),
        "classification": classification.value,
        "novelty_authority": novelty_authority,
        "wording_is_novelty_authority": False,
        "issues": issues,
    }
    return _with_receipt_hash(body)


def audit_social_novelty_receipt(receipt: object) -> dict[str, Any]:
    issues: list[str] = []
    if not isinstance(receipt, Mapping):
        return {"ready": False, "issues": ["SOCIAL_NOVELTY_RECEIPT_MISSING"]}
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("schema_version") != SOCIAL_NOVELTY_SCHEMA:
        issues.append("SOCIAL_NOVELTY_SCHEMA_INVALID")
    if hash_payload(body) != receipt.get("receipt_sha256"):
        issues.append("SOCIAL_NOVELTY_HASH_MISMATCH")
    if receipt.get("wording_is_novelty_authority") is not False:
        issues.append("PROMOTIONAL_WORDING_MUST_NOT_ASSERT_NOVELTY")
    classification = receipt.get("classification")
    if classification not in {item.value for item in SocialNoveltyClass}:
        issues.append("SOCIAL_NOVELTY_CLASSIFICATION_INVALID")
    if classification in {
        SocialNoveltyClass.RECIRCULATED.value,
        SocialNoveltyClass.NOT_NEW_ARTIFACT.value,
    } and receipt.get("novelty_authority") != 0.0:
        issues.append("STALE_SOCIAL_CLAIM_HAS_NONZERO_NOVELTY_AUTHORITY")
    return {"ready": not issues, "issues": issues, "classification": classification}


def v21_reference_and_recirculation_receipts() -> dict[str, Any]:
    """Materialize the two concrete receipts behind the V21 source audit."""

    repo_facts = {
        "source_id": "anthropics/financial-services",
        "source_url": "https://github.com/anthropics/financial-services",
        "license": "Apache-2.0",
        "declared_role": "reference agents and workflow templates",
    }
    reference = build_reference_architecture_receipt(
        source_id=repo_facts["source_id"],
        source_url=repo_facts["source_url"],
        source_hash=hash_payload(repo_facts),
        explicitly_reference_only=True,
        local_validation_refs=(
            "tests/test_economic_assumption_registry_v21.py",
            "tests/test_typed_control_events_v21.py",
            "tests/test_untrusted_projection_air_gap_v21.py",
        ),
        local_behavior_tests_pass=True,
        local_safety_tests_pass=True,
    )
    target = {
        "source_ref": "https://x.com/cyrilxbt/status/2093890723279979004?s=43",
        "published_at": "2026-08-30T02:37:05.695Z",
        "claim": "just open sourced the entire Wall Street workflow",
    }
    artifact = {
        "source_ref": "Anthropic Agents for financial services announcement",
        "released_at": "2026-05-05T00:00:00Z",
    }
    prior = {
        "source_ref": "cyrilxbt substantially identical post 2026-06-17",
        "published_at": "2026-06-17T00:00:00Z",
        "substantially_identical": True,
    }
    recirculation = build_social_novelty_receipt(
        target_source_ref=target["source_ref"],
        target_source_hash=hash_payload(target),
        target_published_at=target["published_at"],
        underlying_artifact_ref=artifact["source_ref"],
        underlying_artifact_hash=hash_payload(artifact),
        underlying_artifact_released_at=artifact["released_at"],
        novelty_terms=("just", "open sourced"),
        prior_matches=(
            {
                **prior,
                "source_hash": hash_payload(prior),
            },
        ),
    )
    return {"reference_architecture": reference, "social_novelty": recirculation}


__all__ = [
    "LocalPatternStatus",
    "REFERENCE_RECEIPT_SCHEMA",
    "ReferenceArchitectureClass",
    "SOCIAL_NOVELTY_SCHEMA",
    "SocialNoveltyClass",
    "audit_reference_architecture_receipt",
    "audit_social_novelty_receipt",
    "build_reference_architecture_receipt",
    "build_social_novelty_receipt",
    "v21_reference_and_recirculation_receipts",
]
