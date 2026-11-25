"""Cheap freshness checks for persistent collector data heartbeats.

This module only stats heartbeat files configured in the canonical collector
registry (some can be large). It never reads payloads or starts/stops workers.
"""
from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from .collecteur_registry import COLLECTEURS_CAMPAGNE, REGISTRE

_ONE_SHOT_FLAGS = frozenset({"--une-fois", "--max-ticks"})
_SKIP_NAMES = frozenset({"copy-vault-checkpoints"})
_BAD_HEARTBEAT_STATES = frozenset({"STALE", "MISSING", "UNREADABLE", "FUTURE"})


def _heartbeat_specs() -> dict[str, tuple[str, float]]:
    specs: dict[str, tuple[str, float]] = {}
    for collector in (*REGISTRE, *COLLECTEURS_CAMPAGNE):
        name = collector.get("nom")
        heartbeat = collector.get("heartbeat")
        args = collector.get("args") or ()
        if (
            not isinstance(name, str)
            or not name
            or name in _SKIP_NAMES
            or not isinstance(heartbeat, str)
            or not heartbeat
            or Path(heartbeat).suffix.lower() == ".lock"
            or any(flag in args for flag in _ONE_SHOT_FLAGS)
        ):
            continue
        try:
            interval_s = float(collector.get("intervalle_s", 30))
        except (TypeError, ValueError):
            interval_s = 30.0
        if not math.isfinite(interval_s) or interval_s <= 0:
            interval_s = 30.0
        # A little slack absorbs ordinary scheduling and disk delays. The cap
        # prevents long polling intervals from hiding a dead continuous feed.
        threshold_s = max(120.0, min(900.0, interval_s * 4.0))
        specs[name] = (heartbeat, threshold_s)
    return specs


HEARTBEAT_SPECS = _heartbeat_specs()


def collector_heartbeat_health(
    root: str | Path,
    active_names: Iterable[str],
    *,
    now_s: float | None = None,
) -> dict[str, dict[str, Any]]:
    """Return heartbeat freshness for active registered persistent collectors.

    The check is intentionally metadata-only (`stat`): large heartbeat JSON
    files are not parsed on the ETA refresh path. A fresh heartbeat proves only
    that its writer is updating the heartbeat, not that valid market events
    arrived or that the source is SAFE.
    """
    root_path = Path(root)
    now = time.time() if now_s is None else float(now_s)
    if not math.isfinite(now):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for name in sorted({str(item) for item in active_names if item}):
        spec = HEARTBEAT_SPECS.get(name)
        if spec is None:
            continue
        relative_path, threshold_s = spec
        path = root_path / relative_path
        base = {"path": relative_path, "threshold_s": threshold_s}
        try:
            modified_s = path.stat().st_mtime
        except FileNotFoundError:
            result[name] = {**base, "status": "MISSING", "age_s": None}
            continue
        except OSError:
            result[name] = {**base, "status": "UNREADABLE", "age_s": None}
            continue

        age_s = now - modified_s
        if age_s < -30.0:
            result[name] = {
                **base, "status": "FUTURE", "age_s": None,
                "future_by_s": round(-age_s, 1),
            }
        elif age_s > threshold_s:
            result[name] = {
                **base, "status": "STALE", "age_s": round(age_s, 1),
            }
        else:
            result[name] = {
                **base, "status": "FRESH", "age_s": round(max(0.0, age_s), 1),
            }
    return result


def stale_collector_heartbeats(
    health: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """List active collectors whose configured data heartbeat is not fresh."""
    return sorted(
        name for name, row in health.items()
        if row.get("status") in _BAD_HEARTBEAT_STATES
    )


__all__ = [
    "HEARTBEAT_SPECS",
    "collector_heartbeat_health",
    "stale_collector_heartbeats",
]
