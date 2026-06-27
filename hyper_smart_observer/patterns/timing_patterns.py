from __future__ import annotations

from datetime import datetime


def hour_distribution(timestamps: list[datetime]) -> dict[int, int]:
    distribution = {hour: 0 for hour in range(24)}
    for timestamp in timestamps:
        distribution[timestamp.hour] += 1
    return distribution
