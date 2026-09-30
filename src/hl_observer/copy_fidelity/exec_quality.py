"""Execution-quality analysis (S5 — V9, pm-backtest A2 / polybot).

Compares realised vs expected slippage, computes fill ratio and a queue
estimate, and grades the execution GOOD / ACCEPTABLE / POOR.

SAFETY: pure post-hoc analysis of *paper* fills against expectations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecQuality:
    slippage_excess_bps: float
    fill_ratio: float
    queue_estimate: float | None
    grade: str


def fill_ratio(filled_qty: float, intended_qty: float) -> float:
    if intended_qty <= 0:
        return 0.0
    return min(1.0, max(0.0, filled_qty / intended_qty))


def evaluate_exec_quality(
    *,
    realized_slippage_bps: float,
    expected_slippage_bps: float,
    filled_qty: float,
    intended_qty: float,
    queue_position: float | None = None,
    excess_warn_bps: float = 10.0,
    excess_bad_bps: float = 30.0,
    min_fill_ratio: float = 0.8,
) -> ExecQuality:
    excess = realized_slippage_bps - expected_slippage_bps
    ratio = fill_ratio(filled_qty, intended_qty)

    if excess >= excess_bad_bps or ratio < min_fill_ratio:
        grade = "POOR"
    elif excess >= excess_warn_bps:
        grade = "ACCEPTABLE"
    else:
        grade = "GOOD"

    return ExecQuality(
        slippage_excess_bps=excess,
        fill_ratio=ratio,
        queue_estimate=queue_position,
        grade=grade,
    )
