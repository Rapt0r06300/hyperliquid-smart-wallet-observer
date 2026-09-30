from __future__ import annotations

from hyper_smart_observer.scoring.risk_metrics import safe_divide


def calculate_winrate(results: list[float]) -> float | None:
    usable = [value for value in results if value != 0]
    if not usable:
        return None
    wins = sum(1 for value in usable if value > 0)
    return safe_divide(wins, len(usable))


def calculate_average_win(results: list[float]) -> float | None:
    wins = [value for value in results if value > 0]
    if not wins:
        return None
    return sum(wins) / len(wins)


def calculate_average_loss(results: list[float]) -> float | None:
    losses = [value for value in results if value < 0]
    if not losses:
        return None
    return sum(losses) / len(losses)
