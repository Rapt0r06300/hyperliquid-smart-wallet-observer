"""Trade-tick replay (V12 capability R, repo 11): order + dedupe trade ticks.

Guarantees a deterministic, time-ordered, duplicate-free stream of trade ticks for the
backtester (no event ever arrives "before" an earlier one). Pure / no network.
"""

from __future__ import annotations

import math


def _key(t: dict):
    ts = t.get("ts_ms", 0)
    seq = t.get("seq", 0)
    if isinstance(ts, bool) or isinstance(seq, bool) or int(ts) < 0 or int(seq) < 0:
        raise ValueError("trade tick timestamps and sequences must be non-negative")
    return (int(ts), int(seq))


def _dedupe_id(t: dict) -> str:
    if t.get("id") is not None:
        return str(t["id"])
    return f"{t.get('ts_ms',0)}:{t.get('px')}:{t.get('sz')}:{t.get('side')}"


def replay_trade_ticks(ticks: list[dict], *, dedupe: bool = True) -> list[dict]:
    for tick in ticks:
        if not isinstance(tick, dict):
            raise ValueError("trade ticks must be mappings")
        for key in ("px", "sz"):
            if tick.get(key) is not None and (
                isinstance(tick.get(key), bool) or not math.isfinite(float(tick[key]))
                or float(tick[key]) <= 0.0
            ):
                raise ValueError("trade price and size must be finite and > 0")
    ordered = sorted(ticks, key=_key)
    if not dedupe:
        return ordered
    seen: set[str] = set()
    out: list[dict] = []
    for t in ordered:
        k = _dedupe_id(t)
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


def is_monotonic(ticks: list[dict]) -> bool:
    last = None
    for t in ticks:
        k = _key(t)
        if last is not None and k < last:
            return False
        last = k
    return True


__all__ = ["replay_trade_ticks", "is_monotonic"]
