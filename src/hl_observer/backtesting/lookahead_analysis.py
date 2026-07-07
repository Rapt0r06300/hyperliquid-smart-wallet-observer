"""Lookahead analysis facade for V14 framework profiles."""

from __future__ import annotations

from dataclasses import asdict

from hl_observer.backtest.no_lookahead_guard import LookaheadViolation, find_lookahead_violations


def lookahead_analysis_report(events, *, min_gap_ms: int = 0) -> dict[str, object]:
    violations = find_lookahead_violations(events, min_gap_ms=min_gap_ms)
    return {
        "ok": not violations,
        "violation_count": len(violations),
        "violations": [asdict(item) for item in violations[:100]],
        "min_gap_ms": int(min_gap_ms),
        "paper_only": True,
    }


__all__ = ["LookaheadViolation", "lookahead_analysis_report"]
