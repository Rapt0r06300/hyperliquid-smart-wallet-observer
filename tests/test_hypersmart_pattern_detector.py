from hyper_smart_observer.patterns.pattern_detector import PatternDetector


def test_pattern_detector_refuses_insufficient_data():
    result = PatternDetector(min_evidence=5).detect_from_pnls("0x" + "a" * 40, [1.0, -1.0])[0]

    assert result.pattern_type == "INSUFFICIENT_DATA"
    assert result.confidence == 0.0


def test_pattern_detector_research_only_message():
    result = PatternDetector(min_evidence=3).detect_from_pnls("0x" + "a" * 40, [2.0, 1.0, -0.5])[0]

    assert "research" in result.research_only_message.lower()
