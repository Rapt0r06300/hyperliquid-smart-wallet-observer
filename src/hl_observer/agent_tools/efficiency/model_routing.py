"""Deterministic task routing policy; it never calls a model or external service."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum


class ExecutionTier(str, Enum):
    FAST = "FAST"
    REVIEW = "REVIEW"
    DEEP = "DEEP"


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    tier: ExecutionTier
    max_iterations: int
    max_context_tokens: int
    reason: str
    requires_full_tests: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "tier": self.tier.value,
            "max_iterations": self.max_iterations,
            "max_context_tokens": self.max_context_tokens,
            "reason": self.reason,
            "requires_full_tests": self.requires_full_tests,
        }


def route_task(
    description: str,
    changed_files: Iterable[str] = (),
    *,
    failure_count: int = 0,
    requires_security_review: bool = False,
) -> RoutingDecision:
    text = description.lower()
    files = tuple(changed_files)
    security = requires_security_review or any(word in text for word in ("security", "secret", "execution", "risk", "paper"))
    complex_words = any(word in text for word in ("architecture", "migration", "concurrency", "schema", "replay", "economic", "cross-repo"))
    if security or complex_words or len(files) > 8 or failure_count >= 2:
        return RoutingDecision(ExecutionTier.DEEP, 8, 24_000, "SECURITY_OR_COMPLEXITY", True)
    if len(files) <= 2 and len(text.split()) <= 24 and failure_count == 0:
        return RoutingDecision(ExecutionTier.FAST, 3, 8_000, "SMALL_LOCAL_CHANGE", False)
    return RoutingDecision(ExecutionTier.REVIEW, 5, 16_000, "STANDARD_CHANGE", len(files) > 4)


__all__ = ["ExecutionTier", "RoutingDecision", "route_task"]
