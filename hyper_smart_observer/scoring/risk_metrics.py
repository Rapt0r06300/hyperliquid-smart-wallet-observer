from __future__ import annotations

import math
from statistics import mean, pstdev


def safe_divide(numerator: float, denominator: float, default: float | None = None) -> float | None:
    """Divide without raising on zero or invalid inputs."""

    try:
        if denominator == 0:
            return default
        return numerator / denominator
    except (TypeError, ValueError, ZeroDivisionError):
        return default


def calculate_profit_factor(gross_profit: float, gross_loss: float) -> float | None:
    """Return gross profit divided by absolute gross loss.

    A wallet with no observed losses is not automatically "infinite"; the
    sample may simply be incomplete, so this returns None instead of inf.
    """

    loss = abs(gross_loss)
    if loss == 0:
        return None
    return gross_profit / loss


def calculate_sharpe(returns: list[float], risk_free_rate: float = 0.0, min_points: int = 2) -> float | None:
    usable = _finite_values(returns)
    if len(usable) < min_points:
        return None
    excess = [value - risk_free_rate for value in usable]
    deviation = pstdev(excess)
    if deviation == 0:
        return None
    return mean(excess) / deviation


def calculate_sortino(
    returns: list[float], target_return: float = 0.0, min_points: int = 2
) -> float | None:
    usable = _finite_values(returns)
    if len(usable) < min_points:
        return None
    downside = [min(0.0, value - target_return) for value in usable if value < target_return]
    if not downside:
        return None
    downside_deviation = math.sqrt(mean([value * value for value in downside]))
    if downside_deviation == 0:
        return None
    return (mean(usable) - target_return) / downside_deviation


def calculate_calmar(total_return: float | None, max_drawdown: float | None) -> float | None:
    if total_return is None or max_drawdown is None or max_drawdown <= 0:
        return None
    return total_return / max_drawdown


def _finite_values(values: list[float]) -> list[float]:
    return [float(value) for value in values if isinstance(value, (int, float)) and math.isfinite(value)]
