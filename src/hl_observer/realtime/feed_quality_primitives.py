"""Pure feed-quality normalization, percentile and identity helpers."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def stable_event_id(payload: Any) -> str:
    """Return a deterministic hash for deduplication and provenance."""
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalise_levels(levels: Iterable[Any]) -> dict[float, float]:
    result: dict[float, float] = {}
    for level in levels:
        if isinstance(level, Mapping):
            price_raw = level.get("px", level.get("price"))
            size_raw = level.get("sz", level.get("size"))
        elif (
            isinstance(level, Sequence)
            and not isinstance(level, (str, bytes))
            and len(level) >= 2
        ):
            price_raw, size_raw = level[0], level[1]
        else:
            raise ValueError("invalid book level")
        price = float(price_raw)
        size = float(size_raw)
        if not math.isfinite(price) or price <= 0:
            raise ValueError("invalid book price")
        if not math.isfinite(size) or size < 0:
            raise ValueError("invalid book size")
        if size > 0:
            result[price] = size
    return result
