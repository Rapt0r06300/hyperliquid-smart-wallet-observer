"""Lightweight live wallet scoring loop for paper-only copy selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class LiveWalletScore:
    wallet: str
    wallet_score: float
    copyability_score: float
    reason_codes: tuple[str, ...]


def score_live_wallets(
    rows: Iterable[dict[str, object]],
    *,
    min_events: int = 3,
) -> tuple[LiveWalletScore, ...]:
    """Compute a deterministic online score from local observations.

    The score is intentionally bounded and research-only. It does not create a
    trade; it only feeds the mirror candidate gate.
    """

    out: list[LiveWalletScore] = []
    for row in rows:
        wallet = str(row.get("wallet") or "").lower()
        events = int(row.get("events") or row.get("fill_count") or 0)
        positive = int(row.get("positive_events") or row.get("wins") or 0)
        pnl = float(row.get("paper_pnl") or row.get("realized_pnl") or 0.0)
        recency = max(0.0, min(1.0, float(row.get("recency_score") or 0.0)))
        reasons: list[str] = []
        if events < min_events:
            reasons.append("INSUFFICIENT_LIVE_EVENTS")
        winrate = positive / max(1, events)
        pnl_component = 0.15 if pnl > 0 else -0.10 if pnl < 0 else 0.0
        wallet_score = max(0.0, min(1.0, 0.25 + 0.45 * winrate + 0.20 * recency + pnl_component))
        copyability = max(0.0, min(1.0, 0.35 * wallet_score + 0.35 * recency + 0.30 * min(1.0, events / 20.0)))
        out.append(
            LiveWalletScore(
                wallet=wallet,
                wallet_score=round(wallet_score, 8),
                copyability_score=round(copyability, 8),
                reason_codes=tuple(reasons),
            )
        )
    return tuple(out)


__all__ = ["LiveWalletScore", "score_live_wallets"]
