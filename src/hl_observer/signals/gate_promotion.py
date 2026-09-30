"""Gate promotion (V12 #140): shadow → authoritative merge for the unified copy gate.

The unified gate (`signals.copy_decision.evaluate_copy_candidate`) runs in SHADOW by
default — it reports a verdict but does not change the real decision. This helper makes
the promotion **opt-in** and **safe by construction**:

* It is a STRICTER INTERSECTION: it can only turn an accepting score into a reject when
  the unified gate also rejects. It can NEVER turn a reject into an accept, so enabling
  it cannot make the engine open trades it would otherwise refuse.
* Default (``authoritative=False``) returns the score reason unchanged (pure shadow).

Read-only / paper-only: this decides a *simulation* verdict, never a real order.
"""

from __future__ import annotations

ACCEPT_MARKER = "EDGE_OK_FOR_LOCAL_SIMULATION"


def merge_authoritative_decision(
    *,
    score_reason: str,
    v12_accepted: bool | None,
    v12_reason: str | None,
    authoritative: bool,
    accept_marker: str = ACCEPT_MARKER,
) -> str:
    """Return the effective decision_reason after optional promotion.

    Shadow (authoritative=False): ``score_reason`` unchanged.
    Authoritative: if the score accepts but the unified gate rejects, the gate's reason
    becomes binding. Any other combination is left as-is.
    """
    if authoritative and score_reason == accept_marker and v12_accepted is False:
        return str(v12_reason or "REJECT_V12_GATE")
    return score_reason


__all__ = ["merge_authoritative_decision", "ACCEPT_MARKER"]
