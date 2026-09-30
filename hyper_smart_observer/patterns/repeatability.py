from __future__ import annotations


def has_repeatability(evidence_count: int, min_count: int = 10) -> bool:
    return evidence_count >= min_count
