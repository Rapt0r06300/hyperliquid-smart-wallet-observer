"""Golden temporal-integrity scenarios for H—T-39.

These tests intentionally exercise public fail-closed temporal contracts instead of
reimplementing them.  The corpus is deterministic and must remain small enough to run
in every normal CI shard.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from hl_observer.research.empirical_memory import (
    EmpiricalEvidence,
    EmpiricalEvidenceState,
    EmpiricalMemoryUnverifiedError,
    evidence_state,
    require_revalidated_evidence,
)
from hl_observer.testing.lookahead_detector import analyser_source, lit_le_futur


def _causal_expanding_mean(values: list[float]) -> list[float]:
    out: list[float] = []
    total = 0.0
    for index, value in enumerate(values, start=1):
        total += value
        out.append(total / index)
    return out


def _leaking_global_mean(values: list[float]) -> list[float]:
    mean = sum(values) / len(values)
    return [mean for _ in values]


@dataclass(frozen=True)
class _Law:
    cle: str
    evidence: tuple[EmpiricalEvidence, ...]


def test_golden_differential_accepts_past_only_series_transform() -> None:
    values = [100.0, 101.0, 103.0, 102.0, 105.0, 107.0]

    assert lit_le_futur(_causal_expanding_mean, values, i=2) is False


def test_golden_differential_rejects_global_future_leakage() -> None:
    values = [100.0, 101.0, 103.0, 102.0, 105.0, 107.0]

    assert lit_le_futur(_leaking_global_mean, values, i=2) is True


def test_golden_ast_scanner_flags_unwindowed_temporal_aggregate() -> None:
    source = """
def suspicious(prices):
    return prices.mean()
"""

    suspicions = analyser_source(source, fichier="golden_future_leak.py")

    assert len(suspicions) == 1
    assert suspicions[0].fichier == "golden_future_leak.py"
    assert "LOOKAHEAD" in suspicions[0].motif


def test_golden_knowledge_as_of_rejects_future_evidence() -> None:
    evidence = EmpiricalEvidence(
        uri="repo://golden/future.json",
        sha256="a" * 64,
        observed_on=date(2026, 9, 11),
        revalidated_on=date(2026, 9, 11),
        max_age_days=30,
    )
    law = _Law(cle="golden_future_knowledge", evidence=(evidence,))
    as_of = date(2026, 9, 10)

    assert evidence_state(law, as_of=as_of) is EmpiricalEvidenceState.UNVERIFIABLE
    with pytest.raises(EmpiricalMemoryUnverifiedError):
        require_revalidated_evidence(law, as_of=as_of)


def test_golden_knowledge_as_of_accepts_fresh_past_evidence() -> None:
    evidence = EmpiricalEvidence(
        uri="repo://golden/past.json",
        sha256="b" * 64,
        observed_on=date(2026, 9, 1),
        revalidated_on=date(2026, 9, 9),
        max_age_days=30,
    )
    law = _Law(cle="golden_past_knowledge", evidence=(evidence,))
    as_of = date(2026, 9, 10)

    assert evidence_state(law, as_of=as_of) is EmpiricalEvidenceState.REVALIDATED
    assert require_revalidated_evidence(law, as_of=as_of) == (evidence,)
