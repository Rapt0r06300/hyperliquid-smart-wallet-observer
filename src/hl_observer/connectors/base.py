"""Read-only source adapter (V12, repo 13): normalize external sources to common models.

A connector READS a source and normalizes it to the common dict model. It has NO execution
surface (no submit/place/order/sign/send) — enforced by tests. read_only is True.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


@dataclass(frozen=True, slots=True)
class ConnectorSnapshot:
    """A bounded, read-only source snapshot.

    The shape is intentionally plain JSON-friendly. It can be produced by a
    real Hyperliquid read-only source, a recorded fixture, or a replay. It does
    not contain any venue action surface.
    """

    source: str
    observed_at_ms: int
    fills: tuple[dict[str, Any], ...] = ()
    positions: tuple[dict[str, Any], ...] = ()
    mids: dict[str, float] = field(default_factory=dict)
    public_flows: tuple[dict[str, Any], ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()

    @property
    def read_only(self) -> bool:
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "observed_at_ms": self.observed_at_ms,
            "fills": list(self.fills),
            "positions": list(self.positions),
            "mids": dict(self.mids),
            "public_flows": list(self.public_flows),
            "raw": dict(self.raw),
            "evidence_refs": list(self.evidence_refs),
            "read_only": True,
        }


class ReadOnlySourceAdapter:
    read_only = True
    name = "base"

    def normalize_fill(self, raw: dict) -> dict:  # pragma: no cover - interface
        raise NotImplementedError


class ReadOnlyConnector(ReadOnlySourceAdapter):
    """Hummingbot-style connector contract, stripped to observation only."""

    def snapshot_from_payload(
        self,
        *,
        observed_at_ms: int,
        fills: tuple[dict[str, Any], ...] = (),
        positions: tuple[dict[str, Any], ...] = (),
        mids: dict[str, float] | None = None,
        public_flows: tuple[dict[str, Any], ...] = (),
        raw: dict[str, Any] | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> ConnectorSnapshot:
        normalized_fills = tuple(self.normalize_fill(fill) for fill in fills)
        return ConnectorSnapshot(
            source=self.name,
            observed_at_ms=int(observed_at_ms),
            fills=normalized_fills,
            positions=tuple(dict(item) for item in positions),
            mids={str(k).upper(): float(v) for k, v in (mids or {}).items()},
            public_flows=tuple(dict(item) for item in public_flows),
            raw=dict(raw or {}),
            evidence_refs=tuple(evidence_refs),
        )


__all__ = ["ConnectorSnapshot", "ReadOnlyConnector", "ReadOnlySourceAdapter", "to_common_fill"]
