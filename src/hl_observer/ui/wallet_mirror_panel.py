"""Read-only wallet mirror panel payloads."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from typing import Iterable

from hl_observer.copy_mode.wallet_mirror_runtime import MirrorCandidate
from hl_observer.paper_trading.mirror_paper_executor import MirrorPaperExecutionResult


def build_wallet_mirror_panel(
    *,
    candidates: Iterable[MirrorCandidate] = (),
    executions: Iterable[MirrorPaperExecutionResult] = (),
    rejected: Iterable[dict[str, object]] = (),
    now_ms: int | None = None,
) -> dict[str, object]:
    candidate_rows = [candidate.as_dict() for candidate in candidates]
    execution_rows = [execution.as_dict() for execution in executions]
    rejected_rows = [dict(row) for row in rejected]
    reasons = Counter()
    for row in candidate_rows:
        for reason in row.get("reason_codes", []) or []:
            reasons[str(reason)] += 1
    for row in execution_rows:
        for reason in row.get("reason_codes", []) or []:
            reasons[str(reason)] += 1
    for row in rejected_rows:
        for reason in row.get("reason_codes", []) or []:
            reasons[str(reason)] += 1
    return {
        "title": "Wallet mirror paper",
        "read_only": True,
        "paper_only": True,
        "external_action": False,
        "generated_at_ms": int(now_ms) if now_ms is not None else None,
        "candidates_seen": len(candidate_rows),
        "paper_executions": sum(1 for row in execution_rows if row.get("accepted") is True),
        "rejected": len(rejected_rows) + sum(1 for row in execution_rows if row.get("accepted") is not True),
        "top_reasons": [{"reason": reason, "count": count} for reason, count in reasons.most_common(20)],
        "candidates": candidate_rows[:50],
        "executions": execution_rows[:50],
        "rejected_rows": rejected_rows[:50],
        "empty": not candidate_rows and not execution_rows and not rejected_rows,
    }


def build_wallet_mirror_summary(result) -> dict[str, object]:
    """Accept a MultiWalletSessionResult-like object."""

    accepted = tuple(getattr(result, "accepted", ()) or ())
    rejected = tuple(getattr(result, "rejected", ()) or ())
    return {
        "groups_seen": int(getattr(result, "groups_seen", 0) or 0),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "paper_only": True,
        "external_action": False,
        "accepted_preview": [item.as_dict() if hasattr(item, "as_dict") else asdict(item) for item in accepted[:10]],
        "rejected_preview": [dict(item) for item in rejected[:10]],
    }


__all__ = ["build_wallet_mirror_panel", "build_wallet_mirror_summary"]
