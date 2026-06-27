"""Runner contract (V12 capability R, repo 11): validate backtest inputs before running.

Refuses inputs that would produce dishonest results: a LIVE run context (backtests must be
BACKTEST/REPLAY/TEST_FIXTURE), empty event sets, or any lookahead leak (data newer than the
decision). Pure / deterministic.
"""

from __future__ import annotations

from hl_observer.backtest.no_lookahead_guard import find_lookahead_violations
from hl_observer.storage.run_context import RunContext


def validate_runner_inputs(run_context, events, *, min_gap_ms: int = 0) -> list[str]:
    """Return a list of violation strings (empty = valid)."""
    violations: list[str] = []
    ctx = run_context if isinstance(run_context, RunContext) else RunContext(str(run_context).upper())
    if ctx == RunContext.LIVE:
        violations.append("RUN_CONTEXT_MUST_NOT_BE_LIVE_FOR_BACKTEST")
    if not events:
        violations.append("NO_EVENTS")
    leaks = find_lookahead_violations(events, min_gap_ms=min_gap_ms)
    if leaks:
        violations.append(f"LOOKAHEAD_LEAK={len(leaks)}")
    return violations


def assert_runner_inputs(run_context, events, *, min_gap_ms: int = 0) -> None:
    v = validate_runner_inputs(run_context, events, min_gap_ms=min_gap_ms)
    if v:
        raise ValueError("invalid backtest inputs: " + "; ".join(v))


__all__ = ["validate_runner_inputs", "assert_runner_inputs"]
