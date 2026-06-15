from __future__ import annotations

import math
from datetime import datetime
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz; UTC = _tz.utc


def calculate_history_days(first_seen: datetime | None, last_seen: datetime | None) -> float | None:
    if first_seen is None or last_seen is None:
        return None
    return max(0.0, (last_seen - first_seen).total_seconds() / 86_400)


def calculate_sample_quality_score(
    *,
    usable_fills: int,
    skipped_fills: int,
    closed_pnl_points: int,
    history_days: float | None,
    min_fills: int,
    min_closed_pnl_points: int,
    min_history_days: float,
) -> float:
    fill_score = min(1.0, usable_fills / max(1, min_fills))
    pnl_score = min(1.0, closed_pnl_points / max(1, min_closed_pnl_points))
    history_score = min(1.0, (history_days or 0.0) / max(1.0, min_history_days))
    total = usable_fills + skipped_fills
    skipped_penalty = 0.0 if total == 0 else min(0.5, skipped_fills / total)
    score = ((0.40 * fill_score) + (0.35 * pnl_score) + (0.25 * history_score)) * 100.0
    return max(0.0, min(100.0, score * (1.0 - skipped_penalty)))


def calculate_recency_score(
    last_seen: datetime | None,
    *,
    half_life_days: float,
    now: datetime | None = None,
) -> float:
    if last_seen is None or half_life_days <= 0:
        return 0.0
    now = now or datetime.now(UTC)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    age_days = max(0.0, (now - last_seen).total_seconds() / 86_400)
    return max(0.0, min(100.0, 100.0 * math.pow(0.5, age_days / half_life_days)))


def calculate_consistency_score(pnl_values: list[float], max_drawdown: float | None) -> float:
    usable = [float(value) for value in pnl_values if isinstance(value, (int, float)) and math.isfinite(value)]
    if len(usable) < 2:
        return 0.0
    total_abs = sum(abs(value) for value in usable)
    concentration = max(abs(value) for value in usable) / total_abs if total_abs else 1.0
    positive_ratio = sum(1 for value in usable if value > 0) / len(usable)
    drawdown_penalty = 0.0
    if max_drawdown is not None and total_abs > 0:
        drawdown_penalty = min(0.7, max_drawdown / total_abs)
    score = (0.55 * (1.0 - concentration)) + (0.25 * positive_ratio) + (0.20 * (1.0 - drawdown_penalty))
    return max(0.0, min(100.0, score * 100.0))
