"""NO_TRADE analysis & explorer (V12 - cablage taxonomie vers dashboard K).

Consumes the raw refusal-reason strings the runtime actually logs, normalizes them
through the canonical taxonomy (signals/no_trade_taxonomy), and builds a
dashboard-ready "NO_TRADE Explorer" payload: counts by canonical code / category /
severity, retriable share, and the human messages. Unrecognized literals are
surfaced honestly under unknown_reasons (never invented, never hidden).

Pure / read-only: aggregates real recorded reasons only; no order, no fabrication.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from hl_observer.signals.no_trade_taxonomy import TAXONOMY, resolve


def no_trade_precision(avoided_losses: int, rejected_count: int) -> float:
    if rejected_count <= 0:
        return 0.0
    return avoided_losses / rejected_count


def normalize_reasons(raw_reasons: Iterable[str]) -> tuple[list[str], list[str]]:
    """Split raw refusal strings into (canonical codes, unrecognized literals)."""
    canonical: list[str] = []
    unknown: list[str] = []
    for raw in raw_reasons:
        try:
            canonical.append(resolve(raw).value)
        except ValueError:
            unknown.append(str(raw))
    return canonical, unknown


def build_no_trade_explorer(raw_reasons: Iterable[str], *, now_ms: int | None = None) -> dict:
    """Build the read-only NO_TRADE Explorer payload from real refusal reasons."""
    canonical, unknown = normalize_reasons(raw_reasons)
    code_counts = Counter(canonical)
    unknown_counts = Counter(unknown)

    by_code: list[dict] = []
    by_category: Counter = Counter()
    by_severity: Counter = Counter()
    retriable_count = 0
    for code, n in sorted(code_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        meta = TAXONOMY[code]
        by_code.append({
            "reason_code": code,
            "count": n,
            "severity": meta.severity,
            "category": meta.category,
            "is_retriable": meta.is_retriable,
            "dashboard_message": meta.dashboard_message,
            "next_action": meta.next_action,
        })
        by_category[meta.category] += n
        by_severity[meta.severity] += n
        if meta.is_retriable:
            retriable_count += n

    unknown_rows = [
        {"reason": r, "count": c}
        for r, c in sorted(unknown_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {
        "total": len(canonical) + sum(unknown_counts.values()),
        "recognized": len(canonical),
        "unknown": sum(unknown_counts.values()),
        "by_code": by_code,
        "by_category": dict(by_category),
        "by_severity": dict(by_severity),
        "retriable_count": retriable_count,
        "unknown_reasons": unknown_rows,
        "generated_at_ms": int(now_ms) if now_ms is not None else None,
        "empty": not canonical and not unknown_counts,
    }


__all__ = ["no_trade_precision", "normalize_reasons", "build_no_trade_explorer"]
