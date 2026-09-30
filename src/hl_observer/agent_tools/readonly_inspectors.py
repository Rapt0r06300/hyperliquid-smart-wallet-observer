"""Read-only agent inspectors (V12 capability L).

Concrete, pure implementations behind the read-only tool contracts declared in
``agent_tools/manifest.py``. Each returns a JSON-serializable dict aggregated from
REAL recorded state only (honest empty state when there is nothing). No execution
surface: these functions read and summarize, never place an order or mutate a venue.
"""

from __future__ import annotations

from pathlib import Path

from hl_observer.release.release_readiness import check_release_readiness
from hl_observer.signals.decision_funnel import build_decision_funnel
from hl_observer.validation.no_trade_analyzer import build_no_trade_explorer

# Manifest tool names implemented here (subset of READ_TOOLS).
IMPLEMENTED_READ_TOOLS = ("source_health.read", "dashboard.export")


def _health_row(h) -> dict:
    return {
        "source_id": h.source_id,
        "status": getattr(h.status, "value", str(h.status)),
        "usable": bool(h.usable),
        "age_ms": h.age_ms,
        "samples": h.samples,
        "success_rate": h.success_rate,
        "last_error": h.last_error,
    }


def source_health_read(recorder, *, now_ms: int | None = None) -> dict:
    """source_health.read — provenance/health of every data source (honest empty if none)."""
    if recorder is None:
        return {"tool": "source_health.read", "sources": 0, "by_status": {},
                "usable": 0, "raw_events_stored": 0, "all_health": [], "empty": True}
    summary = recorder.summary(now_ms=now_ms)
    rows = recorder.all_health(now_ms=now_ms)
    return {"tool": "source_health.read", **summary,
            "all_health": [_health_row(h) for h in rows],
            "empty": int(summary.get("sources", 0)) == 0}


def no_trade_explorer_read(raw_reasons, *, now_ms: int | None = None) -> dict:
    return {"tool": "no_trade.explorer", **build_no_trade_explorer(raw_reasons, now_ms=now_ms)}


def decision_funnel_read(decisions, *, now_ms: int | None = None) -> dict:
    return {"tool": "decision.funnel", **build_decision_funnel(decisions, now_ms=now_ms)}


def release_readiness_read(root: str | Path = ".") -> dict:
    return {"tool": "release.readiness", **check_release_readiness(root).to_dict()}


def dashboard_export(*, recorder=None, raw_reasons=(), decisions=(), now_ms: int | None = None) -> dict:
    """dashboard.export — one read-only payload aggregating source health + NO_TRADE + funnel."""
    return {
        "tool": "dashboard.export",
        "source_health": source_health_read(recorder, now_ms=now_ms),
        "no_trade": no_trade_explorer_read(raw_reasons, now_ms=now_ms),
        "funnel": decision_funnel_read(decisions, now_ms=now_ms),
    }


__all__ = [
    "IMPLEMENTED_READ_TOOLS",
    "source_health_read",
    "no_trade_explorer_read",
    "decision_funnel_read",
    "release_readiness_read",
    "dashboard_export",
]
