"""Phase 9: pattern detector returns INSUFFICIENT_DATA (no invented score) when
evidence is sparse, and real patterns with evidence_count otherwise."""

from __future__ import annotations

from hyper_smart_observer.patterns.pattern_detector import PatternDetector

W = "0x" + "f" * 40


def test_sparse_history_is_insufficient_data():
    det = PatternDetector(min_evidence=10)
    results = det.detect_from_pnls(W, [1.0, -2.0, 3.0])
    assert results
    assert results[0].pattern_type == "INSUFFICIENT_DATA"
    assert results[0].confidence == 0.0
    assert results[0].evidence_count == 3


def test_enough_evidence_yields_pattern_with_evidence_count():
    det = PatternDetector(min_evidence=3)
    results = det.detect_from_pnls(W, [1.0, 2.0, -1.0, 3.0, -2.0, 4.0])
    assert all(r.pattern_type != "INSUFFICIENT_DATA" for r in results)
    assert all(r.evidence_count == 6 for r in results)
