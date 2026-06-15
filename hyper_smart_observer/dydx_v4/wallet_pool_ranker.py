from __future__ import annotations

from typing import Any

_CURSOR = 0
_LAST_TOTAL = 0
_LAST_SENT = 0


def _num(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _addr(w: Any) -> str | None:
    a = getattr(w, "address", None)
    return a if isinstance(a, str) and a else None


def wallet_pool_batch(wallets: list[Any], limit: int, scorer, anchor_share: float = 0.55) -> list[tuple[str, float]]:
    global _CURSOR, _LAST_TOTAL, _LAST_SENT
    if not wallets or limit <= 0:
        _LAST_TOTAL = 0
        _LAST_SENT = 0
        return []
    ranked = sorted(wallets, key=lambda w: (scorer(w), _num(getattr(w, "score", 0.0))), reverse=True)
    _LAST_TOTAL = len(ranked)
    anchor_n = max(1, min(len(ranked), int(limit * anchor_share)))
    anchors = ranked[:anchor_n]
    tail = ranked[anchor_n:]
    if not tail:
        out = [(_addr(w), max(scorer(w), _num(getattr(w, "score", 0.0)))) for w in anchors]
        out = [(a, s) for a, s in out if a]
        _LAST_SENT = len(out)
        return out[:limit]
    batch_n = max(1, min(limit - anchor_n, len(tail)))
    start = _CURSOR % len(tail)
    moving = tail[start:start + batch_n]
    if len(moving) < batch_n:
        moving += tail[:batch_n - len(moving)]
    _CURSOR = (start + batch_n) % len(tail)
    merged: dict[str, float] = {}
    for w in anchors + moving:
        a = _addr(w)
        if a:
            merged[a] = max(merged.get(a, 0.0), scorer(w), _num(getattr(w, "score", 0.0)))
    out = sorted(merged.items(), key=lambda x: x[1], reverse=True)[:limit]
    _LAST_SENT = len(out)
    return out


def pool_stats() -> dict:
    return {"cursor": _CURSOR, "last_total": _LAST_TOTAL, "last_sent": _LAST_SENT, "read_only": True, "paper_only": True}


__all__ = ["pool_stats", "wallet_pool_batch"]
