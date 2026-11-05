"""Bounded retry and no-progress detection for local agent loops."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class LoopDecision:
    continue_running: bool
    reason: str
    step: int


@dataclass(slots=True)
class LoopGuard:
    max_steps: int = 8
    max_identical_actions: int = 2
    _steps: int = 0
    _last_action: str = ""
    _identical_count: int = 0
    history: list[str] = field(default_factory=list)

    def observe(self, action: str, *, success: bool = False, acceptance_reached: bool = False) -> LoopDecision:
        self._steps += 1
        fingerprint = hashlib.sha256(str(action).encode("utf-8")).hexdigest()[:16]
        self.history.append(fingerprint)
        if acceptance_reached:
            return LoopDecision(False, "ACCEPTANCE_REACHED", self._steps)
        if success:
            self._last_action = fingerprint
            self._identical_count = 0
            return LoopDecision(True, "PROGRESS_OBSERVED", self._steps)
        if fingerprint == self._last_action:
            self._identical_count += 1
        else:
            self._last_action = fingerprint
            self._identical_count = 1
        if self._steps >= self.max_steps:
            return LoopDecision(False, "MAX_STEPS_REACHED", self._steps)
        if self._identical_count >= self.max_identical_actions:
            return LoopDecision(False, "REPEATED_ACTION_WITHOUT_PROGRESS", self._steps)
        return LoopDecision(True, "CONTINUE_WITHIN_BUDGET", self._steps)


def should_rerun_test(test_id: str, *, source_fingerprint: str, previous_fingerprint: str | None, previous_status: str | None) -> bool:
    del test_id
    if previous_fingerprint != source_fingerprint:
        return True
    return str(previous_status or "").upper() not in {"PASS", "PASSED", "GREEN"}


__all__ = ["LoopDecision", "LoopGuard", "should_rerun_test"]
