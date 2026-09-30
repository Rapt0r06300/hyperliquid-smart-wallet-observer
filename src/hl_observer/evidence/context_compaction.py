"""Context compaction (V12, repo 01): shrink history while PRESERVING decision summaries.

Keeps every decision/NO_TRADE item verbatim; truncates the rest. Pure / deterministic.
"""

from __future__ import annotations


def compact_context(items: list[dict], *, max_other: int = 50) -> dict:
    decisions = [i for i in items if i.get("kind") in {"decision", "no_trade", "exit"}]
    others = [i for i in items if i.get("kind") not in {"decision", "no_trade", "exit"}]
    kept_others = others[-max_other:] if max_other >= 0 else others
    return {
        "decisions": decisions,                  # preserved in full
        "other": kept_others,
        "dropped_other": max(0, len(others) - len(kept_others)),
        "decision_summary_preserved": True,
    }


__all__ = ["compact_context"]
