"""V14 #183 — Promote smart-money gate + depth guard into the binding ENTRY gate.

Combines two known-quality checks: the leader is genuine smart money AND the book is deep
enough to fill cleanly. When authoritative, an accepting score is rejected if EITHER check is
known-false. Unknown (None) never blocks. Stricter intersection: only reduces trades. Pure.
"""

from __future__ import annotations

ACCEPT_MARKER = "EDGE_OK_FOR_LOCAL_SIMULATION"
REJECT_SMART_MONEY = "REJECT_NOT_SMART_MONEY"
REJECT_DEPTH = "REJECT_DEPTH_GUARD"


def apply_entry_quality_promotion(
    *,
    score_reason: str,
    smart_money_ok: bool | None,
    depth_ok: bool | None,
    authoritative: bool,
    accept_marker: str = ACCEPT_MARKER,
) -> str:
    if authoritative and score_reason == accept_marker:
        if smart_money_ok is False:
            return REJECT_SMART_MONEY
        if depth_ok is False:
            return REJECT_DEPTH
    return score_reason


__all__ = ["ACCEPT_MARKER", "REJECT_SMART_MONEY", "REJECT_DEPTH", "apply_entry_quality_promotion"]
