"""Public research connector (V12, repo 13): normalize a public-research datum (read-only)."""

from __future__ import annotations

from hl_observer.connectors.base import ReadOnlySourceAdapter, to_common_fill


class PublicResearchConnector(ReadOnlySourceAdapter):
    name = "public_research"

    def normalize_fill(self, raw: dict) -> dict:
        return to_common_fill(
            coin=raw.get("symbol") or raw.get("coin") or "UNKNOWN",
            side=str(raw.get("direction", "UNKNOWN")).upper(),
            px=raw.get("price") or 0.0,
            sz=raw.get("amount") or raw.get("size") or 0.0,
            ts_ms=raw.get("ts") or raw.get("time") or 0,
            source="public_research",
        )


__all__ = ["PublicResearchConnector"]
