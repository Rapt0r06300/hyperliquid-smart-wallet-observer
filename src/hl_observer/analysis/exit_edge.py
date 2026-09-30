from __future__ import annotations


def exit_quality_score(*, average_win: float | None, average_loss: float | None) -> float:
    if average_win is None or average_loss is None or average_loss <= 0:
        return 50.0 if average_win else 0.0
    return max(0.0, min(100.0, average_win / average_loss * 50.0))
