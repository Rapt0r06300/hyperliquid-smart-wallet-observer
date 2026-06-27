"""Adaptive paper-only sizing for the live Hyperliquid simulation.

The simulator is intentionally local-only: this module never places orders and
never talks to an exchange. It only decides how much virtual margin a paper
entry may use after looking at recent local outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable

from hl_observer.risk.adaptive_sizing import compute_size_pct, size_to_notional

EXIT_ACTION_MARKERS = ("CLOSE", "REDUCE", "STOP", "TAKE_PROFIT", "TRAILING")


@dataclass(frozen=True, slots=True)
class AdaptivePaperSize:
    requested_margin_usdt: float
    final_margin_usdt: float
    cap_margin_usdt: float
    consecutive_losses: int
    consecutive_wins: int
    confidence: float
    size_pct: float
    session_pnl_usdt: float
    reason: str
    enabled: bool = True

    def to_log_fields(self) -> dict[str, Any]:
        fields = asdict(self)
        fields["adaptive_size_reason"] = fields.pop("reason")
        fields["adaptive_sizing"] = True
        return fields


def realized_exit_pnls(events: Iterable[dict[str, Any]]) -> list[float]:
    """Return realized paper exit PnLs from the local decision ledger."""

    pnls: list[float] = []
    for row in events:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "").upper() != "LOCAL_REPLAY":
            continue
        action = str(row.get("bot_replay_action") or row.get("paper_action_type") or "").upper()
        if not any(marker in action for marker in EXIT_ACTION_MARKERS):
            continue
        try:
            pnl = float(row.get("estimated_net_pnl_usdc") or 0.0)
        except (TypeError, ValueError):
            continue
        pnls.append(pnl)
    return pnls


def outcome_streaks(pnls: Iterable[float]) -> tuple[int, int]:
    """Return consecutive losses and wins from the end of a realized PnL series."""

    values = list(pnls)
    losses = 0
    wins = 0
    for pnl in reversed(values):
        if pnl < 0:
            if wins:
                break
            losses += 1
        elif pnl > 0:
            if losses:
                break
            wins += 1
        else:
            continue
    return losses, wins


def adaptive_paper_margin(
    *,
    requested_margin_usdt: float,
    equity_usdt: float,
    recent_events: Iterable[dict[str, Any]],
    edge_remaining_bps: float,
    liquidity_score: float,
    consensus_wallets: int,
    min_margin_usdt: float = 5.0,
    max_margin_usdt: float = 50.0,
    enabled: bool = True,
) -> AdaptivePaperSize:
    """Cap paper entry margin using streak, edge, liquidity and consensus.

    The goal is not to force a positive PnL. It is to avoid repeating full-size
    entries after local losses when the edge is only marginal.
    """

    requested = max(0.0, float(requested_margin_usdt or 0.0))
    if requested <= 0:
        return AdaptivePaperSize(
            requested_margin_usdt=0.0,
            final_margin_usdt=0.0,
            cap_margin_usdt=0.0,
            consecutive_losses=0,
            consecutive_wins=0,
            confidence=0.0,
            size_pct=0.0,
            session_pnl_usdt=0.0,
            reason="NO_REQUESTED_MARGIN",
            enabled=enabled,
        )
    if not enabled:
        return AdaptivePaperSize(
            requested_margin_usdt=round(requested, 6),
            final_margin_usdt=round(min(requested, max_margin_usdt), 6),
            cap_margin_usdt=round(max_margin_usdt, 6),
            consecutive_losses=0,
            consecutive_wins=0,
            confidence=1.0,
            size_pct=0.0,
            session_pnl_usdt=0.0,
            reason="ADAPTIVE_SIZING_DISABLED",
            enabled=False,
        )

    pnls = realized_exit_pnls(recent_events)
    losses, wins = outcome_streaks(pnls)
    session_pnl = sum(pnls)
    edge_component = min(0.35, max(0.0, float(edge_remaining_bps or 0.0)) / 120.0)
    liquidity_component = min(0.2, max(0.0, float(liquidity_score or 0.0)) * 0.2)
    consensus_component = min(0.25, max(0, int(consensus_wallets or 0) - 1) * 0.08)
    confidence = min(1.0, max(0.05, 0.25 + edge_component + liquidity_component + consensus_component))
    sizing = compute_size_pct(
        consecutive_losses=losses,
        consecutive_wins=wins,
        confidence=confidence,
    )
    cap = min(max_margin_usdt, size_to_notional(sizing.size_pct, max(0.0, float(equity_usdt or 0.0))))
    reason = "ADAPTIVE_SIZE_OK"
    if session_pnl < 0:
        cap *= 0.85
        reason = "SESSION_NEGATIVE_SIZE_REDUCED"
    if losses >= 2:
        cap *= 0.75
        reason = "LOSS_STREAK_SIZE_REDUCED"
    if losses >= 4:
        cap *= 0.5
        reason = "SEVERE_LOSS_STREAK_SIZE_REDUCED"
    cap = max(0.0, cap)
    if cap < min_margin_usdt:
        return AdaptivePaperSize(
            requested_margin_usdt=round(requested, 6),
            final_margin_usdt=0.0,
            cap_margin_usdt=round(cap, 6),
            consecutive_losses=losses,
            consecutive_wins=wins,
            confidence=round(confidence, 6),
            size_pct=round(sizing.size_pct, 6),
            session_pnl_usdt=round(session_pnl, 6),
            reason="ADAPTIVE_SIZE_BELOW_MINIMUM_AFTER_LOSSES",
        )
    final_margin = min(requested, cap, max_margin_usdt)
    return AdaptivePaperSize(
        requested_margin_usdt=round(requested, 6),
        final_margin_usdt=round(final_margin, 6),
        cap_margin_usdt=round(cap, 6),
        consecutive_losses=losses,
        consecutive_wins=wins,
        confidence=round(confidence, 6),
        size_pct=round(sizing.size_pct, 6),
        session_pnl_usdt=round(session_pnl, 6),
        reason=reason if final_margin < requested else "ADAPTIVE_SIZE_OK",
    )
