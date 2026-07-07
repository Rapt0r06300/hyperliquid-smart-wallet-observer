"""D3 — Garde 2e source : arbitrage/funding exige >= 2 sources fraîches, sinon NO_TRADE.

Une opportunité cross-source n'est valide que confirmée par une seconde source réelle. Pur.
"""

from __future__ import annotations


def fresh_sources(sources: dict, *, max_age_ms: float = 15000.0) -> list[str]:
    """sources: {name: age_ms}. Renvoie les noms de sources assez fraîches."""
    return [name for name, age in (sources or {}).items()
            if age is not None and float(age) <= max_age_ms]


def require_two_sources(sources: dict, *, max_age_ms: float = 15000.0) -> tuple[bool, str]:
    fresh = fresh_sources(sources, max_age_ms=max_age_ms)
    if len(fresh) >= 2:
        return True, "TWO_SOURCES_OK"
    return False, f"NO_TRADE_SECOND_SOURCE_MISSING(fresh={len(fresh)})"


__all__ = ["fresh_sources", "require_two_sources"]
