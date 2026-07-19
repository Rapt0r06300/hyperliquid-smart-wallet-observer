"""Breakdown LIVE des refus depuis les événements ledger en mémoire.

Câblage vague 1 (AUDIT-B / T36): version temps réel du diagnostic
`build_refusal_breakdown` (CLI, sur logs). Pur, sans I/O: consomme la liste
d'événements du UiState. Destiné au dashboard v2 (T49) et à l'estimateur du
coût des refus. Anti-blocage: on VOIT quel gate refuse, combien, et sur quels
coins — au lieu de le subir en silence.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable
from hl_observer.ops.echec_silencieux import noter as _noter_echec

REFUSAL_STATUSES = {"REJECT_NO_TRADE"}
REFUSAL_ACTION_TYPES = {"NO_TRADE"}


def build_live_refusal_breakdown(
    ledger_events: Iterable[dict[str, Any]],
    *,
    top_reasons: int = 8,
    top_coins_per_reason: int = 3,
) -> dict[str, Any]:
    """Agrège les refus par raison avec les coins les plus touchés."""

    reasons: Counter[str] = Counter()
    coins_by_reason: dict[str, Counter[str]] = defaultdict(Counter)
    notional_refused: dict[str, float] = defaultdict(float)
    total = 0
    for event in ledger_events or []:
        if not isinstance(event, dict):
            continue
        is_refusal = (
            str(event.get("status") or "") in REFUSAL_STATUSES
            or str(event.get("paper_action_type") or "") in REFUSAL_ACTION_TYPES
        )
        if not is_refusal:
            continue
        reason = str(event.get("reason") or "UNKNOWN_REASON")
        coin = str(event.get("coin") or "?").upper()
        reasons[reason] += 1
        coins_by_reason[reason][coin] += 1
        try:
            notional_refused[reason] += abs(float(event.get("leader_notional_usdc") or 0.0))
        except (TypeError, ValueError):
            _noter_echec("hl_observer/ui/refusal_live.py:47")
        total += 1
    rows = [
        {
            "reason": reason,
            "count": count,
            "share": round(count / total, 4) if total else 0.0,
            "top_coins": [f"{c}×{n}" for c, n in coins_by_reason[reason].most_common(top_coins_per_reason)],
            "refused_notional_usdc": round(notional_refused[reason], 2),
        }
        for reason, count in reasons.most_common(top_reasons)
    ]
    return {
        "total_refusals": total,
        "distinct_reasons": len(reasons),
        "rows": rows,
        "read_only": True,
        "paper_only": True,
    }


__all__ = ["build_live_refusal_breakdown"]
