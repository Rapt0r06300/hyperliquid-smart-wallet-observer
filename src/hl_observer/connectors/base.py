"""Read-only source adapter (V12, repo 13): normalize external sources to common models.

A connector READS a source and normalizes it to the common dict model. It has NO execution
surface (no submit/place/order/sign/send) — enforced by tests. read_only is True.
"""

from __future__ import annotations


def to_common_fill(*, coin, side, px, sz, ts_ms, source) -> dict:
    """The canonical normalized-fill shape every connector must emit."""
    return {
        "coin": str(coin).upper(),
        "side": str(side).upper(),
        "px": float(px),
        "sz": float(sz),
        "ts_ms": int(ts_ms),
        "source": str(source),
    }


class ReadOnlySourceAdapter:
    read_only = True
    name = "base"

    def normalize_fill(self, raw: dict) -> dict:  # pragma: no cover - interface
        raise NotImplementedError


__all__ = ["ReadOnlySourceAdapter", "to_common_fill"]
