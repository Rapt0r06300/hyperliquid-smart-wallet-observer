import pytest
from hyper_smart_observer.scoring.confidence_math import wilson_lower_bound

@pytest.mark.contract
def test_contract_wilson_lower_bound_accuracy():
    """
    Contract: Verify Wilson lower bound calculation for statistical confidence.
    """
    # 80 wins out of 100
    score = wilson_lower_bound(80, 100)
    assert 0.70 < score < 0.80 # Lower bound is significantly below 0.80 due to sample size

    # 8 wins out of 10 (same 80% rate, but much lower confidence)
    score_small = wilson_lower_bound(8, 10)
    assert score_small < score # 8/10 should have lower bound than 80/100

    # 0 wins
    assert wilson_lower_bound(0, 10) == 0.0

@pytest.mark.contract
def test_contract_skill_vs_luck_formula_presence():
    """
    Contract: Ensure skill vs luck scoring logic is available.
    """
    from hyper_smart_observer.scoring.confidence_math import calculate_skill_score
    score = calculate_skill_score(0.75, 30)
    assert score > 0
    assert isinstance(score, float)
