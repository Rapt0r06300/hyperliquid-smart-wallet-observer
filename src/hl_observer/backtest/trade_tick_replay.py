"""Trade-tick replay (V12 capability R, repo 11): order + dedupe trade ticks.

Guarantees a deterministic, time-ordered, duplicate-free stream of trade ticks for the
backtester (no event ever arrives "before" an earlier one). Pure / no network.
"""

from __future__ import annotations


def _key(t: dict):
    return (int(t.get("ts_ms", 0)), int(t.get("seq", 0)))


def _dedupe_id(t: dict) -> str:
    if t.get("id") is not None:
        return str(t["id"])
    return f"{t.get('ts_ms',0)}:{t.get('px')}:{t.get('sz')}:{t.get('side')}"


def replay_trade_ticks(ticks: list[dict], *, dedupe: bool = True) -> list[dict]:
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
