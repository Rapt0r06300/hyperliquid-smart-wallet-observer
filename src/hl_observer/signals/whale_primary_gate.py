"""V14 #168 — Promote the whale-fill signal to a PRIMARY entry source.

The freshest, most reliable copy trigger is a real, recent, significant leader FILL
(see ``whale_fill_signal``). This gate lets that signal become *binding*: when made
authoritative, a candidate that the score would accept is REJECTED unless a primary
whale fill backs it. Like every promotion in this codebase it is a stricter
intersection — it can only ever *reduce* trades, never create one.

* ``authoritative=False`` (default / shadow): no-op, returns the score reason unchanged.
* ``whale_primary is None`` (unknown / signal unavailable): no-op — we never block on
  missing information, only on a *known* absence (``False``).

Read-only / paper-only: this decides a simulation verdict, never a real order.
"""

from __future__ import annotations

ACCEPT_MARKER = "EDGE_OK_FOR_LOCAL_SIMULATION"
REJECT_REASON = "REJECT_NO_PRIMARY_WHALE_SIGNAL"


def apply_whale_primary_promotion(
    *,
    score_reason: str,
    whale_primary: bool | None,
    authoritative: bool,
    accept_marker: str = ACCEPT_MARKER,
) -> str:
    """Stricter intersection on the primary whale-fill signal.

    Only turns an ACCEPT into a reject when we *know* there is no primary whale signal
    (``whale_primary is False``). Never turns a reject into an accept. Shadow = no-op.
    """
    if (
        authoritative
        and score_reason == accept_marker
        and whale_primary is False
    ):
        return REJECT_REASON
    return score_reason


__all__ = ["ACCEPT_MARKER", "REJECT_REASON", "apply_whale_primary_promotion"]
