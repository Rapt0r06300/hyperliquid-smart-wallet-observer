from __future__ import annotations

from math import isfinite, sqrt


def wilson_lower_bound(wins: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    phat = wins / total
    denominator = 1 + z * z / total
    centre = phat + z * z / (2 * total)
    margin = z * sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    return (centre - margin) / denominator


def one_big_win_dependency(top_trade_pnl_share: float, threshold: float = 0.30) -> bool:
    return top_trade_pnl_share > threshold


def compare_skill_vs_luck(
    *,
    leader_wins: int,
    leader_total: int,
    baseline_wins: int,
    baseline_total: int,
    activity_matched: bool = True,
    exposure_matched: bool = True,
) -> dict[str, object]:
    """Compare a leader with an activity/exposure-matched controlled baseline.

    The lower Wilson bounds are deliberately used instead of raw win rates: a
    small sample cannot manufacture skill evidence.  Matching metadata is a
    prerequisite; missing or invalid observations remain fail-closed.
    """
    values = (leader_wins, leader_total, baseline_wins, baseline_total)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        return {"status": "UNMEASURABLE", "reason": "counts_must_be_integers"}
    if any(value < 0 for value in values) or leader_wins > leader_total or baseline_wins > baseline_total:
        return {"status": "UNMEASURABLE", "reason": "invalid_win_counts"}
    if not isinstance(activity_matched, bool) or not isinstance(exposure_matched, bool):
        return {"status": "UNMEASURABLE", "reason": "matching_flags_must_be_boolean"}
    if not activity_matched or not exposure_matched:
        return {"status": "UNMEASURABLE", "reason": "baseline_not_matched"}
    if leader_total == 0 or baseline_total == 0:
        return {"status": "MORE_DATA", "reason": "empty_sample"}
    leader_rate = leader_wins / leader_total
    baseline_rate = baseline_wins / baseline_total
    leader_lower = wilson_lower_bound(leader_wins, leader_total)
    baseline_lower = wilson_lower_bound(baseline_wins, baseline_total)
    return {
        "status": "PROVEN",
        "leader_win_rate": round(leader_rate, 8),
        "baseline_win_rate": round(baseline_rate, 8),
        "leader_wilson_lower": round(leader_lower, 8),
        "baseline_wilson_lower": round(baseline_lower, 8),
        "skill_excess": round(leader_lower - baseline_lower, 8),
        "skill_supported": leader_lower > baseline_lower,
        "activity_matched": True,
        "exposure_matched": True,
    }


def activity_matched_placebo_receipt(**kwargs: object) -> dict[str, object]:
    """ECO-165 wrapper for an activity/exposure-matched placebo comparison."""
    result = compare_skill_vs_luck(**kwargs)
    result.update(
        contract="ECO-165-activity-matched-placebo",
        placebo_group_required=True,
        paper_read_only=True,
        promotion="DISABLED_UNTIL_REVIEW",
    )
    return result


__all__ = ["wilson_lower_bound", "one_big_win_dependency", "compare_skill_vs_luck", "activity_matched_placebo_receipt"]
