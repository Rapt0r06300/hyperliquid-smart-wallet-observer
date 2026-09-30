"""D2 — Liveness de source : LIVE / FIXTURE / STALE / EMPTY (état vide honnête).

Empêche de présenter une fixture ou une donnée périmée comme du live. Pur.
"""

from __future__ import annotations

LIVE = "LIVE"
FIXTURE = "FIXTURE"
STALE = "STALE"
EMPTY = "EMPTY"


def classify_source(*, count: int, age_ms: float, is_fixture: bool, max_age_ms: float = 15000.0) -> str:
    if is_fixture:
        return FIXTURE
    if count <= 0:
        return EMPTY
    if age_ms > max_age_ms:
        return STALE
    return LIVE


def live_or_no_trade(*, count: int, age_ms: float, is_fixture: bool, max_age_ms: float = 15000.0) -> tuple[bool, str]:
    """(ok, reason). Seul LIVE autorise ; sinon NO_TRADE avec la cause exacte."""
    status = classify_source(count=count, age_ms=age_ms, is_fixture=is_fixture, max_age_ms=max_age_ms)
    if status == LIVE:
        return True, LIVE
    return False, f"NO_TRADE_{status}"


__all__ = ["LIVE", "FIXTURE", "STALE", "EMPTY", "classify_source", "live_or_no_trade"]
