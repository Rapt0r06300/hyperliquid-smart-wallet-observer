"""Fail-closed provenance and freshness contract for empirical memory.

This module deliberately has no authority over ACTIVE_SCOPE.  It only decides whether
an empirical claim carries enough immutable, recent evidence to be *reused as evidence*.
The caller remains responsible for the higher-level strategy/scope decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
import re
from typing import Protocol, runtime_checkable

EMPIRICAL_MEMORY_IS_ACTIVE_SCOPE_AUTHORITY = False
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class EmpiricalEvidenceState(StrEnum):
    REVALIDATED = "REVALIDATED"
    STALE = "STALE"
    UNVERIFIABLE = "UNVERIFIABLE"


class EmpiricalMemoryUnverifiedError(RuntimeError):
    """Raised when empirical memory is requested without fresh verifiable evidence."""


@dataclass(frozen=True, slots=True)
class EmpiricalEvidence:
    """Immutable pointer to one piece of evidence supporting an empirical law.

    ``uri`` identifies the evidence location, while ``sha256`` binds the claim to exact
    bytes. ``revalidated_on`` is the last date on which that exact evidence was checked
    against the law. ``max_age_days`` defines the allowed reuse horizon.
    """

    uri: str
    sha256: str
    observed_on: date
    revalidated_on: date
    max_age_days: int

    def is_structurally_verifiable(self, *, as_of: date) -> bool:
        if not str(self.uri).strip():
            return False
        if _SHA256_RE.fullmatch(str(self.sha256).strip()) is None:
            return False
        if not isinstance(self.observed_on, date) or not isinstance(self.revalidated_on, date):
            return False
        if isinstance(self.max_age_days, bool) or not isinstance(self.max_age_days, int):
            return False
        if self.max_age_days <= 0:
            return False
        if self.observed_on > as_of or self.revalidated_on > as_of:
            return False
        if self.revalidated_on < self.observed_on:
            return False
        return True

    def is_stale(self, *, as_of: date) -> bool:
        return (as_of - self.revalidated_on).days > self.max_age_days


@runtime_checkable
class _LawWithEvidence(Protocol):
    evidence: tuple[EmpiricalEvidence, ...]


def _evidence_tuple(law: object) -> tuple[EmpiricalEvidence, ...]:
    value = getattr(law, "evidence", ())
    if not isinstance(value, tuple):
        return ()
    if not all(isinstance(item, EmpiricalEvidence) for item in value):
        return ()
    return value


def evidence_state(law: object, *, as_of: date | None = None) -> EmpiricalEvidenceState:
    """Return the reusable-evidence state for ``law`` without ever promoting scope.

    Precedence is fail-closed: malformed/future evidence is UNVERIFIABLE even when some
    other evidence is merely stale; otherwise any stale item makes the law STALE; only a
    non-empty set of structurally valid, fresh items is REVALIDATED.
    """

    reference_date = as_of or date.today()
    evidence = _evidence_tuple(law)
    if not evidence:
        return EmpiricalEvidenceState.UNVERIFIABLE

    if any(not item.is_structurally_verifiable(as_of=reference_date) for item in evidence):
        return EmpiricalEvidenceState.UNVERIFIABLE
    if any(item.is_stale(as_of=reference_date) for item in evidence):
        return EmpiricalEvidenceState.STALE
    return EmpiricalEvidenceState.REVALIDATED


def require_revalidated_evidence(
    law: object, *, as_of: date | None = None
) -> tuple[EmpiricalEvidence, ...]:
    """Return exact evidence only when the whole empirical claim is freshly revalidated."""

    reference_date = as_of or date.today()
    state = evidence_state(law, as_of=reference_date)
    if state is not EmpiricalEvidenceState.REVALIDATED:
        key = getattr(law, "cle", "<unknown>")
        raise EmpiricalMemoryUnverifiedError(
            f"empirical law {key!r} is {state.value}; fresh hashed evidence is required"
        )
    return _evidence_tuple(law)


__all__ = [
    "EMPIRICAL_MEMORY_IS_ACTIVE_SCOPE_AUTHORITY",
    "EmpiricalEvidence",
    "EmpiricalEvidenceState",
    "EmpiricalMemoryUnverifiedError",
    "evidence_state",
    "require_revalidated_evidence",
]
