import math

def wilson_lower_bound(successes: int, total: int, confidence: float = 0.95) -> float:
    """
    Calculates the Wilson score interval lower bound.
    Used to measure win-rate confidence (Skill vs Luck).
    """
    if total <= 0:
        return 0.0

    z = 1.96 # Approx for 95% confidence
    if confidence == 0.99:
        z = 2.576

    p_hat = successes / total
    numerator = p_hat + (z**2) / (2 * total) - z * math.sqrt((p_hat * (1 - p_hat) + (z**2) / (4 * total)) / total)
    denominator = 1 + (z**2) / total

    return max(0.0, numerator / denominator)

def calculate_skill_score(win_rate_lower_bound: float, history_days: float) -> float:
    """Combines statistical win-rate confidence with history length."""
    return min(100.0, win_rate_lower_bound * 80.0 + min(20.0, history_days / 2.0))
