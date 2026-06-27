"""Experiment runner (V12 capability R, repo 11): run a backtest experiment honestly.

Validates inputs via the runner contract, then walks events in time order, passing each
decide_fn ONLY the past events (no lookahead), and produces a report. Pure.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from hl_observer.backtest.runner_contract import assert_runner_inputs


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    name: str
    run_context: str
    total_events: int
    decisions: tuple[dict, ...] = field(default_factory=tuple)
    accepted: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "run_context": self.run_context,
            "total_events": self.total_events,
            "accepted": self.accepted,
            "decisions": list(self.decisions),
        }


def run_experiment(
    name: str,
    run_context,
    events: list[dict],
    decide_fn: Callable[[dict, list[dict]], dict],
    *,
    min_gap_ms: int = 0,
) -> ExperimentResult:
    assert_runner_inputs(run_context, events, min_gap_ms=min_gap_ms)
    ordered = sorted(events, key=lambda e: int(e.get("decision_ts_ms", e.get("data_ts_ms", 0))))
    decisions: list[dict] = []
    accepted = 0
    for i, ev in enumerate(ordered):
        past = ordered[:i]                       # only the past is visible
        d = decide_fn(ev, past) or {}
        decisions.append(d)
        if d.get("accepted"):
            accepted += 1
    rc = run_context.value if hasattr(run_context, "value") else str(run_context)
    return ExperimentResult(name=name, run_context=rc, total_events=len(ordered),
                            decisions=tuple(decisions), accepted=accepted)


__all__ = ["ExperimentResult", "run_experiment"]
