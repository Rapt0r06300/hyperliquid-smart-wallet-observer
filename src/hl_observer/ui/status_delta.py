"""FLUID — Deltas incrémentaux entre deux payloads status (hyperfluidité UI).

Au lieu de re-render tout le dashboard à chaque tick, on n'envoie/n'applique que
ce qui a changé. Pur, déterministe. Sert le re-render ciblé côté client (16ms/frame).
"""

from __future__ import annotations

from typing import Any

_WATCHED = (
    "net_pnl_usdt", "equity_usdt", "realized_pnl_usdt", "unrealized_pnl_usdt",
    "open_positions", "open_exposure_usdt", "winrate_pct", "closed_trades",
    "winning_trades", "losing_trades", "engine_running", "server_running",
)


def compute_status_delta(prev: dict[str, Any] | None, curr: dict[str, Any]) -> dict[str, Any]:
    """Champs surveillés qui ont changé + fingerprint léger des positions."""

    prev = prev if isinstance(prev, dict) else {}
    curr = curr if isinstance(curr, dict) else {}
    changed: dict[str, Any] = {}
    for key in _WATCHED:
        if prev.get(key) != curr.get(key):
            changed[key] = curr.get(key)
    prev_fp = _positions_fingerprint(prev.get("positions"))
    curr_fp = _positions_fingerprint(curr.get("positions"))
    positions_changed = prev_fp != curr_fp
    return {
        "changed_fields": changed,
        "positions_changed": positions_changed,
        "has_changes": bool(changed) or positions_changed,
        "positions_fingerprint": curr_fp,
    }


def _positions_fingerprint(positions: Any) -> tuple:
    if not isinstance(positions, list):
        return ()
    fp = []
    for p in positions:
        if not isinstance(p, dict):
            continue
        fp.append((
            str(p.get("coin") or ""),
            str(p.get("side") or p.get("direction") or ""),
            round(float(p.get("notional_usdt") or p.get("copied_notional_usdt") or 0.0), 2),
        ))
    return tuple(sorted(fp))


__all__ = ["compute_status_delta"]
