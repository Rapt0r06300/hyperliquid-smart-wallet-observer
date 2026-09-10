from __future__ import annotations

from datetime import date

import pytest

from hl_observer.research.empirical_memory import (
    EMPIRICAL_MEMORY_IS_ACTIVE_SCOPE_AUTHORITY,
    EmpiricalEvidence,
    EmpiricalEvidenceState,
    EmpiricalMemoryUnverifiedError,
    evidence_state,
    require_revalidated_evidence,
)
from hl_observer.research.lois_mesurees import Loi, VERDICT_REFUTE


def _law(*, evidence: tuple[EmpiricalEvidence, ...] = ()) -> Loi:
    return Loi(
        cle="unit_test_law",
        titre="Test law",
        verdict=VERDICT_REFUTE,
        chiffre="1.0 bps",
        date="2026-09-01",
        condition_de_reouverture="new evidence",
        mots_cles=("unit-test",),
        ou_verifier="tests/fixtures/evidence.json",
        evidence=evidence,
    )


def _digest() -> str:
    return "a" * 64


def test_empirical_memory_can_never_authorize_active_scope() -> None:
    assert EMPIRICAL_MEMORY_IS_ACTIVE_SCOPE_AUTHORITY is False


def test_missing_evidence_fails_closed() -> None:
    law = _law()

    assert evidence_state(law, as_of=date(2026, 9, 10)) is EmpiricalEvidenceState.UNVERIFIABLE
    with pytest.raises(EmpiricalMemoryUnverifiedError):
        require_revalidated_evidence(law, as_of=date(2026, 9, 10))


def test_missing_or_invalid_digest_fails_closed() -> None:
    law = _law(
        evidence=(
            EmpiricalEvidence(
                uri="repo://tests/fixtures/evidence.json",
                sha256="not-a-sha256",
                observed_on=date(2026, 9, 1),
                revalidated_on=date(2026, 9, 9),
                max_age_days=30,
            ),
        )
    )

    assert evidence_state(law, as_of=date(2026, 9, 10)) is EmpiricalEvidenceState.UNVERIFIABLE


def test_stale_evidence_fails_closed() -> None:
    law = _law(
        evidence=(
            EmpiricalEvidence(
                uri="repo://tests/fixtures/evidence.json",
                sha256=_digest(),
                observed_on=date(2026, 8, 1),
                revalidated_on=date(2026, 8, 1),
                max_age_days=30,
            ),
        )
    )

    assert evidence_state(law, as_of=date(2026, 9, 10)) is EmpiricalEvidenceState.STALE
    with pytest.raises(EmpiricalMemoryUnverifiedError):
        require_revalidated_evidence(law, as_of=date(2026, 9, 10))


def test_fresh_hashed_evidence_is_revalidated() -> None:
    evidence = EmpiricalEvidence(
        uri="repo://tests/fixtures/evidence.json",
        sha256=_digest(),
        observed_on=date(2026, 9, 1),
        revalidated_on=date(2026, 9, 9),
        max_age_days=30,
    )
    law = _law(evidence=(evidence,))

    assert evidence_state(law, as_of=date(2026, 9, 10)) is EmpiricalEvidenceState.REVALIDATED
    assert require_revalidated_evidence(law, as_of=date(2026, 9, 10)) == (evidence,)


def test_future_revalidation_date_is_unverifiable() -> None:
    law = _law(
        evidence=(
            EmpiricalEvidence(
                uri="repo://tests/fixtures/evidence.json",
                sha256=_digest(),
                observed_on=date(2026, 9, 1),
                revalidated_on=date(2026, 9, 11),
                max_age_days=30,
            ),
        )
    )

    assert evidence_state(law, as_of=date(2026, 9, 10)) is EmpiricalEvidenceState.UNVERIFIABLE
