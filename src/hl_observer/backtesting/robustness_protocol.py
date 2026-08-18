"""Pure anti-overfit protocol helpers used by the final pre-run gate.

The holdout is a veto only: candidate ranking is frozen before OOS/forward is
read. Cost/latency stress and alternate-universe partitions are deterministic
and never touch live execution.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any


def stress_cost_latency(
    *,
    fees_bps: float,
    slippage_bps: float,
    latency_bps: float,
    multipliers: Sequence[float] = (1.0, 1.5, 2.0),
) -> list[dict[str, float]]:
    values = (float(fees_bps), float(slippage_bps), float(latency_bps))
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("fees/slippage/latency must be finite and non-negative")
    cleaned = tuple(float(v) for v in multipliers)
    if not cleaned or any(not math.isfinite(v) or v < 1.0 for v in cleaned):
        raise ValueError("stress multipliers must be finite and >= 1")
    out: list[dict[str, float]] = []
    for multiplier in cleaned:
        out.append(
            {
                "multiplier": multiplier,
                "fees_bps": values[0] * multiplier,
                "slippage_bps": values[1] * multiplier,
                "latency_bps": values[2] * multiplier,
                "total_cost_bps": sum(values) * multiplier,
            }
        )
    return out


def alternate_universe_partitions(
    symbols: Sequence[str], *, partitions: int = 3
) -> tuple[tuple[str, ...], ...]:
    """Deterministically create disjoint symbol partitions by stable SHA-256."""
    unique = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    if partitions < 2:
        raise ValueError("partitions must be >= 2")
    if len(unique) < partitions:
        raise ValueError("not enough unique symbols for requested partitions")
    buckets: list[list[str]] = [[] for _ in range(partitions)]
    ranked = sorted(
        unique,
        key=lambda symbol: hashlib.sha256(symbol.encode("utf-8")).hexdigest(),
    )
    for index, symbol in enumerate(ranked):
        buckets[index % partitions].append(symbol)
    return tuple(tuple(bucket) for bucket in buckets)


def freeze_train_selection(train_scores: Mapping[str, float]) -> dict[str, Any]:
    """Freeze a winner from TRAIN only. No holdout value is accepted here."""
    if not train_scores:
        raise ValueError("train_scores cannot be empty")
    clean: dict[str, float] = {}
    for candidate, score in train_scores.items():
        value = float(score)
        if not math.isfinite(value):
            raise ValueError("train score must be finite")
        clean[str(candidate)] = value
    winner = sorted(clean, key=lambda key: (-clean[key], key))[0]
    canonical = json.dumps(clean, sort_keys=True, separators=(",", ":"))
    return {
        "winner": winner,
        "train_scores_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "ranking_source": "TRAIN_ONLY",
        "holdout_used_for_ranking": False,
    }


def apply_holdout_veto(
    frozen_selection: Mapping[str, Any],
    *,
    oos_passed: bool,
    forward_passed: bool,
) -> dict[str, Any]:
    """OOS/forward may only confirm or veto the already frozen train winner."""
    winner = str(frozen_selection.get("winner") or "").strip()
    digest = str(frozen_selection.get("train_scores_sha256") or "")
    if not winner or len(digest) != 64:
        raise ValueError("selection must be frozen from train before holdout")
    if frozen_selection.get("holdout_used_for_ranking") is not False:
        raise ValueError("holdout-contaminated ranking refused")
    accepted = bool(oos_passed and forward_passed)
    return {
        "winner": winner,
        "accepted": accepted,
        "verdict": "CONFIRMED" if accepted else "VETO",
        "retune_allowed": False,
        "holdout_used_for_ranking": False,
        "train_scores_sha256": digest,
    }


__all__ = [
    "alternate_universe_partitions",
    "apply_holdout_veto",
    "freeze_train_selection",
    "stress_cost_latency",
]
