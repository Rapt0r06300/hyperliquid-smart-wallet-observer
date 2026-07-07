"""No-lookahead guard (V12 capability J - backtest sans fuite du futur).

A backtest/replay decision may only use data timestamped at or before the decision
time (optionally older, to model latency). Using data newer than the decision is a
"lookahead" leak and silently inflates results. This guard detects such leaks.

Pure / deterministic: takes timestamps, returns violations. No I/O, no order.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LookaheadViolation:
    index: int
    decision_ts_ms: int
    data_ts_ms: int
    detail: str

    def __str__(self) -> str:
        return f"#{self.index}: {self.detail}"


def _pair(ev) -> tuple[int, int]:
    if isinstance(ev, dict):
        return int(ev["decision_ts_ms"]), int(ev["data_ts_ms"])
    decision_ts_ms, data_ts_ms = ev
    return int(decision_ts_ms), int(data_ts_ms)


def find_lookahead_violations(events, *, min_gap_ms: int = 0) -> list[LookaheadViolation]:
    """Return events whose data is newer than allowed.

    A decision at T may use data with ts <= T - min_gap_ms. With min_gap_ms=0 that is
    simply ts <= T; a positive gap also forbids using data more recent than the latency.
    """
    out: list[LookaheadViolation] = []
    gap = max(0, int(min_gap_ms))
    for i, ev in enumerate(events):
        d_ts, x_ts = _pair(ev)
        cutoff = d_ts - gap
        if x_ts > cutoff:
            out.append(LookaheadViolation(
                index=i,
                decision_ts_ms=d_ts,
                data_ts_ms=x_ts,
                detail=f"data_ts={x_ts} > cutoff={cutoff} (decision={d_ts}, gap={gap})",
            ))
    return out


def assert_no_lookahead(events, *, min_gap_ms: int = 0) -> None:
    v = find_lookahead_violations(events, min_gap_ms=min_gap_ms)
    if v:
        raise AssertionError(
            f"lookahead leak in {len(v)} event(s): " + "; ".join(str(x) for x in v[:5])
        )


__all__ = ["LookaheadViolation", "find_lookahead_violations", "assert_no_lookahead"]
