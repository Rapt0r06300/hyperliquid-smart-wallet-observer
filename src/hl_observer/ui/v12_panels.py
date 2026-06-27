"""Read-only V12 dashboard panels (capability K) — pure payload builders.

Turns data the runtime already has (a CollectionRecorder, the existing NO_TRADE
reason counts, copy decisions) into canonical, dashboard-ready panels:
  * source_health   — provenance/health of every source (deny-by-default visible);
  * no_trade_explorer — refusal reasons enriched via the taxonomy (severity/category);
  * decision_funnel  — acceptance rate + where blocked candidates died.
Pure / read-only: aggregates real recorded values only; honest empty state; no order.
"""

from __future__ import annotations

from collections.abc import Mapping

from hl_observer.agent_tools.readonly_inspectors import source_health_read
from hl_observer.signals.decision_funnel import build_decision_funnel
from hl_observer.validation.no_trade_analyzer import build_no_trade_explorer


def _counts_to_list(reason_counts) -> list[str]:
    """Accept dict[str,int] | list[{'reason','count'}] | list[(reason,count)] | list[str]."""
    pairs: list[tuple[str, int]] = []
    if isinstance(reason_counts, Mapping):
        pairs = [(str(k), int(v)) for k, v in reason_counts.items()]
    else:
        for x in reason_counts or ():
            if isinstance(x, str):
                pairs.append((x, 1))
            elif isinstance(x, Mapping):
                pairs.append((str(x.get("reason")), int(x.get("count", 1))))
            else:
                pairs.append((str(x[0]), int(x[1])))
    out: list[str] = []
    for reason, count in pairs:
        out.extend([reason] * max(0, count))
    return out


def build_no_trade_panel(reason_counts, *, now_ms: int | None = None) -> dict:
    return build_no_trade_explorer(_counts_to_list(reason_counts), now_ms=now_ms)


def build_source_health_panel(recorder, *, now_ms: int | None = None) -> dict:
    return source_health_read(recorder, now_ms=now_ms)


def build_decision_funnel_panel(decisions, *, now_ms: int | None = None) -> dict:
    return build_decision_funnel(decisions, now_ms=now_ms)


def build_v12_panels(*, recorder=None, reason_counts=(), decisions=(), now_ms: int | None = None) -> dict:
    return {
        "source_health": build_source_health_panel(recorder, now_ms=now_ms),
        "no_trade_explorer": build_no_trade_panel(reason_counts, now_ms=now_ms),
        "decision_funnel": build_decision_funnel_panel(decisions, now_ms=now_ms),
        "generated_at_ms": int(now_ms) if now_ms is not None else None,
    }


__all__ = [
    "build_v12_panels",
    "build_no_trade_panel",
    "build_source_health_panel",
    "build_decision_funnel_panel",
]
