"""Offline research helpers for copy-mode analysis.

These helpers are deliberately outside the hot path. They aggregate completed
paper outcomes so the user can inspect why a strategy loses or wins.
"""

from __future__ import annotations

from collections import defaultdict


def summarize_paper_outcomes(rows: list[dict[str, object]]) -> dict[str, object]:
    pnl_by_coin: dict[str, float] = defaultdict(float)
    pnl_by_wallet: dict[str, float] = defaultdict(float)
    reason_counts: dict[str, int] = defaultdict(int)
    total = 0.0
    wins = 0
    losses = 0
    for row in rows:
        pnl = float(row.get("pnl_usdc") or row.get("pnl") or 0.0)
        total += pnl
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1
        coin = str(row.get("coin") or "UNKNOWN").upper()
        wallet = str(row.get("leader_wallet") or row.get("wallet") or "UNKNOWN").lower()
        pnl_by_coin[coin] += pnl
        pnl_by_wallet[wallet] += pnl
        for reason in row.get("reason_codes", ()) or ():
            reason_counts[str(reason)] += 1
    trades = wins + losses
    return {
        "rows": len(rows),
        "trades_with_pnl": trades,
        "net_pnl_usdc": round(total, 8),
        "winrate": round(wins / trades, 8) if trades else None,
        "pnl_by_coin": dict(sorted(pnl_by_coin.items(), key=lambda item: item[1])),
        "pnl_by_wallet": dict(sorted(pnl_by_wallet.items(), key=lambda item: item[1])),
        "reason_counts": dict(sorted(reason_counts.items(), key=lambda item: item[1], reverse=True)),
        "research_only": True,
    }


__all__ = ["summarize_paper_outcomes"]
