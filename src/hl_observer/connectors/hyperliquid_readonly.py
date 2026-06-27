"""Hyperliquid read-only connector (V12, repo 13): normalize a HL /info fill."""

from __future__ import annotations

from hl_observer.connectors.base import ReadOnlySourceAdapter, to_common_fill


def _side(raw: dict) -> str:
    s = str(raw.get("side", "")).strip().lower()
    if s in {"b", "buy", "bid"}:
        return "LONG"
    if s in {"a", "s", "sell", "ask"}:
        return "SHORT"
    d = str(raw.get("dir", "")).lower()
    if "long" in d:
        return "LONG"
    if "short" in d:
        return "SHORT"
    return "UNKNOWN"


class HyperliquidReadonlyConnector(ReadOnlySourceAdapter):
    name = "hyperliquid"

    def normalize_fill(self, raw: dict) -> dict:
        return to_common_fill(
            coin=raw.get("coin") or raw.get("coinName") or "UNKNOWN",
            side=_side(raw),
            px=raw.get("px") or raw.get("price") or 0.0,
            sz=raw.get("sz") or raw.get("size") or 0.0,
            ts_ms=raw.get("time") or raw.get("timestamp") or 0,
            source="hyperliquid",
        )


__all__ = ["HyperliquidReadonlyConnector"]
