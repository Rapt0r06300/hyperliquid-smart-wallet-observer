from __future__ import annotations


def repeatability_score(evidence_count: int, *, min_evidence: int = 10) -> float:
    if evidence_count <= 0:
        return 0.0
    return min(100.0, 100.0 * evidence_count / max(1, min_evidence))
