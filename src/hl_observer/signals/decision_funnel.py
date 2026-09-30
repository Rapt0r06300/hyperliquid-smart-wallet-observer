"""Decision funnel (V12 K - dashboard: "of N candidates, how many copied and why not").

Aggregates a batch of CopyDecision results into an honest funnel: acceptance rate plus
where the blocked candidates died, grouped by canonical NO_TRADE code / category /
severity (reusing the NO_TRADE Explorer). Answers the recurring "why so few openings?"
question with real recorded reasons only. Pure / read-only: no fabrication, honest
empty state.
"""

from __future__ import annotations

from collections.abc import Iterable

from hl_observer.validation.no_trade_analyzer import build_no_trade_explorer


def build_decision_funnel(decisions: Iterable, *, now_ms: int | None = None) -> dict:
    items = list(decisions)
    total = len(items)
    accepted = [d for d in items if getattr(d, "accepted", False)]
    blocked = [d for d in items if not getattr(d, "accepted", False)]
    reason_codes = [d.reason_code for d in blocked if getattr(d, "reason_code", None)]
    explorer = build_no_trade_explorer(reason_codes, now_ms=now_ms)
    return {
        "total": total,
        "accepted": len(accepted),
        "blocked": len(blocked),
        "acceptance_rate": round(len(accepted) / total, 4) if total else 0.0,
        "blocking_reasons": explorer["by_code"],
        "by_category": explorer["by_category"],
        "by_severity": explorer["by_severity"],
        "retriable_blocked": explorer["retriable_count"],
        "generated_at_ms": int(now_ms) if now_ms is not None else None,
        "empty": total == 0,
    }


__all__ = ["build_decision_funnel"]
