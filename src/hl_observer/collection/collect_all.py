"""'Collect everything' orchestration helper (read-only, simulation-only).

Runs a sequence of named read-only collection steps, never stopping the whole
run because one step failed: each step's outcome (ok/detail/error) is captured
so the caller gets maximum data + an honest coverage/source-health summary.
No /exchange, no order, no proxy/rate-limit bypass — only the existing
read-only collectors chained together.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class StepResult:
    name: str
    ok: bool
    detail: str = ""
    error: str | None = None


@dataclass(frozen=True)
class CollectAllReport:
    results: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    @property
    def ran(self) -> int:
        return len(self.results)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    def summary(self) -> str:
        lines = [f"collect-all: {self.ran - self.failed}/{self.ran} steps ok"]
        for r in self.results:
            status = "OK  " if r.ok else "FAIL"
            tail = r.detail if r.ok else (r.error or "error")
            lines.append(f"- {status} {r.name}: {tail}")
        return "\n".join(lines)


def run_steps(steps: list[tuple[str, Callable[[], str]]]) -> CollectAllReport:
    """Run each (name, callable) step. A failing step is recorded, not fatal."""
    results: list[StepResult] = []
    for name, step in steps:
        try:
            detail = step() or ""
            results.append(StepResult(name=name, ok=True, detail=str(detail)))
        except Exception as exc:  # read-only: never let one source kill the run
            results.append(StepResult(name=name, ok=False, error=f"{type(exc).__name__}: {exc}"))
    return CollectAllReport(results=results)
