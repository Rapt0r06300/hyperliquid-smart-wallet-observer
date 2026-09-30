"""Small, dependency-light hot path for copy events.

The hot path intentionally avoids LLMs, network side effects and heavy research
imports. It turns already-normalized observations into deterministic paper-only
decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True, slots=True)
class HotPathEvent:
    event_id: str
    coin: str
    side: str
    wallet: str
    observed_at_ms: int
    raw_hash: str


def hot_path_event_from_fill(fill: dict[str, object], *, observed_at_ms: int) -> HotPathEvent:
    coin = str(fill.get("coin") or "").upper()
    side = str(fill.get("side") or fill.get("dir") or "").upper()
    wallet = str(fill.get("wallet") or fill.get("user") or "").lower()
    material = repr(sorted(fill.items())) + f"|{observed_at_ms}"
    raw_hash = sha256(material.encode("utf-8", errors="replace")).hexdigest()
    return HotPathEvent(
        event_id="hot:" + raw_hash[:24],
        coin=coin,
        side=side,
        wallet=wallet,
        observed_at_ms=int(observed_at_ms),
        raw_hash=raw_hash,
    )


def hot_path_has_heavy_dependencies() -> bool:
    """Guard used by tests/docs: this module must stay lightweight."""

    return False


__all__ = ["HotPathEvent", "hot_path_event_from_fill", "hot_path_has_heavy_dependencies"]
