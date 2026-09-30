"""Slow research path for diagnostics that must not run in hot decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ResearchFinding:
    code: str
    severity: str
    detail: str


def summarize_no_trade_reasons(reasons: Iterable[str]) -> tuple[ResearchFinding, ...]:
    counts: dict[str, int] = {}
    for reason in reasons:
        reason_s = str(reason).strip().upper()
        if reason_s:
            counts[reason_s] = counts.get(reason_s, 0) + 1
    findings = [
        ResearchFinding(
            code=code,
            severity="HIGH" if count >= 3 else "MEDIUM",
            detail=f"{count} occurrence(s) in research path",
        )
        for code, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return tuple(findings)


__all__ = ["ResearchFinding", "summarize_no_trade_reasons"]
