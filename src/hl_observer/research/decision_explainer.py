"""Decision explainer (V12, repo 13): explain a decision using its evidence refs.

Context layer: turns a decision row + evidence references into a human explanation. It does
NOT change the decision (read-only narration). Pure.
"""

from __future__ import annotations


def explain_decision(decision: dict, *, evidence_refs: list[str]) -> dict:
    code = decision.get("reason_code") or ("ACCEPT" if decision.get("accepted") else "NO_TRADE")
    msg = decision.get("dashboard_message") or code
    return {
        "summary": f"{code}: {msg}",
        "accepted": bool(decision.get("accepted", False)),
        "evidence_refs": list(evidence_refs or []),
        "context_only": True,            # never authoritative; never mutates the decision
        "changes_decision": False,
    }


__all__ = ["explain_decision"]
