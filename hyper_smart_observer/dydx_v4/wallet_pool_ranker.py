from __future__ import annotations

from typing import Any

MAX_LIVE_BATCH = 2500
ROTATION_EPOCH_BONUS = 100_000.0
ANCHOR_BONUS = 10_000.0
ROTATING_BONUS = 1_000.0

_CURSOR = 0
_EPOCH = 0
_LAST_TOTAL = 0
_LAST_SENT = 0
_LAST_ANCHORS = 0
_LAST_ROTATED = 0


def _num(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _addr(w: Any) -> str | None:
    a = getattr(w, "address", None)
    return a if isinstance(a, str) and a else None


def _score(w: Any, scorer) -> float:
    return max(float(scorer(w) or 0.0), _num(getattr(w, "score", 0.0)))


def wallet_pool_batch(wallets: list[Any], limit: int, scorer, anchor_share: float = 0.55) -> list[tuple[str, float]]:
    global _CURSOR, _EPOCH, _LAST_TOTAL, _LAST_SENT, _LAST_ANCHORS, _LAST_ROTATED
    if not wallets or limit <= 0:
        _LAST_TOTAL = 0
        _LAST_SENT = 0
        _LAST_ANCHORS = 0
        _LAST_ROTATED = 0
        return []
    ranked = sorted(wallets, key=lambda w: (_score(w, scorer), _num(getattr(w, "score", 0.0))), reverse=True)
    _LAST_TOTAL = len(ranked)
    live_limit = max(1, min(int(limit), MAX_LIVE_BATCH, len(ranked)))
    anchor_n = max(1, min(len(ranked), int(live_limit * max(0.10, min(0.90, anchor_share)))))
    anchors = ranked[:anchor_n]
    tail = ranked[anchor_n:]
    if not tail:
        out = [(_addr(w), _score(w, scorer) + ANCHOR_BONUS + (_EPOCH * ROTATION_EPOCH_BONUS)) for w in anchors]
        out = [(a, s) for a, s in out if a]
        _LAST_SENT = len(out)
        _LAST_ANCHORS = len(out)
        _LAST_ROTATED = 0
        return out[:live_limit]
    batch_n = max(1, min(live_limit - anchor_n, len(tail)))
    start = _CURSOR % len(tail)
    moving = tail[start:start + batch_n]
    if len(moving) < batch_n:
        moving += tail[:batch_n - len(moving)]
    _CURSOR = (start + batch_n) % len(tail)
    _EPOCH += 1
    merged: dict[str, float] = {}
    epoch_boost = _EPOCH * ROTATION_EPOCH_BONUS
    for w in anchors:
        a = _addr(w)
        if a:
            merged[a] = max(merged.get(a, 0.0), _score(w, scorer) + ANCHOR_BONUS + epoch_boost)
    for w in moving:
        a = _addr(w)
        if a:
            merged[a] = max(merged.get(a, 0.0), _score(w, scorer) + ROTATING_BONUS + epoch_boost)
    out = sorted(merged.items(), key=lambda x: x[1], reverse=True)[:live_limit]
    _LAST_SENT = len(out)
    _LAST_ANCHORS = len(anchors)
    _LAST_ROTATED = len(moving)
    return out


def pool_stats() -> dict:
    return {
        "cursor": _CURSOR,
        "epoch": _EPOCH,
        "last_total": _LAST_TOTAL,
        "last_sent": _LAST_SENT,
        "last_anchors": _LAST_ANCHORS,
        "last_rotated": _LAST_ROTATED,
        "max_live_batch": MAX_LIVE_BATCH,
        "read_only": True,
        "paper_only": True,
    }


__all__ = ["MAX_LIVE_BATCH", "pool_stats", "wallet_pool_batch"]
