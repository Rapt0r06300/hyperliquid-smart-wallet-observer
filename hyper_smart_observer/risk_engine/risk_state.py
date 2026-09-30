from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason_code: str
    message: str
    gates: dict[str, bool] = field(default_factory=dict)
    decision_scope: str | None = None
    warnings: list[str] = field(default_factory=list)
