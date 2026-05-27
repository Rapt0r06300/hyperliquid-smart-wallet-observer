from hl_observer.analysis.opening_patterns import OpeningPatternDecision, compute_opening_pattern_stats


def test_opening_patterns_require_min_sample_size():
    stats = compute_opening_pattern_stats([10.0, -5.0], opening_type="MOMENTUM_CHASE_LONG", min_samples=20)

    assert stats.decision == OpeningPatternDecision.REJECT_TOO_FEW_SAMPLES


def test_opening_patterns_score_positive_expectancy_higher():
    positive = compute_opening_pattern_stats([10.0] * 25 + [-2.0] * 5, opening_type="A", min_samples=20)
    negative = compute_opening_pattern_stats([-10.0] * 25 + [2.0] * 5, opening_type="B", min_samples=20)

    assert positive.score > negative.score


def test_opening_patterns_reject_negative_expectancy():
    stats = compute_opening_pattern_stats([-5.0] * 30, opening_type="BAD", min_samples=20)

    assert stats.decision == OpeningPatternDecision.REJECT_NEGATIVE_EXPECTANCY


def test_profit_patterns_do_not_claim_always_wins():
    import inspect
    import hl_observer.analysis.opening_patterns as opening_patterns

    assert "always wins" not in inspect.getsource(opening_patterns).lower()
    assert "gagne toujours" not in inspect.getsource(opening_patterns).lower()
