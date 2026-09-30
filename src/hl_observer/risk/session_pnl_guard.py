"""Paper-only session PnL guard for the live HyperSmart simulation.

The guard is deliberately small and pure: it never talks to a venue and never
creates an order. It only decides whether a *new local paper entry* is allowed
after the current launcher session has already lost money.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class SessionPnlGuardDecision:
    allow_entry: bool
    reason: str
    session_pnl_usdc: float
    soft_loss_usdc: float
    hard_loss_usdc: float
    required_edge_bps: float
    required_consensus_wallets: int
    required_liquidity_score: float
    protection_mode: bool

    def to_log_fields(self) -> dict:
        payload = asdict(self)
        payload["session_pnl_guard"] = True
        return payload


def evaluate_session_pnl_guard(
    *,
    session_pnl_usdc: float,
    starting_equity_usdt: float,
    edge_remaining_bps: float,
    min_edge_required_bps: float,
    consensus_wallets: int,
    liquidity_score: float,
    soft_loss_usdc: float | None = None,
    hard_loss_usdc: float | None = None,
    extra_edge_after_loss_bps: float = 12.0,
    min_consensus_after_loss: int = 3,
    min_liquidity_after_loss: float = 0.45,
) -> SessionPnlGuardDecision:
    """Return an anti-repeat-loss decision for a fresh paper entry.

    A small negative session does not freeze the simulator forever; it raises
    the standard. The next entry must be fresher/stronger and supported by more
    wallets/liquidity. A hard session loss blocks all new entries until the user
    restarts or reviews the session.
    """

    equity = max(0.0, float(starting_equity_usdt or 0.0))
    soft = float(soft_loss_usdc) if soft_loss_usdc is not None else max(0.25, equity * 0.00025)
    hard = float(hard_loss_usdc) if hard_loss_usdc is not None else max(5.0, equity * 0.005)
    pnl = float(session_pnl_usdc or 0.0)
    edge = float(edge_remaining_bps or 0.0)
    base_edge = float(min_edge_required_bps or 0.0)
    consensus = int(consensus_wallets or 0)
    liquidity = float(liquidity_score or 0.0)
    required_edge = base_edge + max(0.0, float(extra_edge_after_loss_bps or 0.0))
    required_consensus = max(1, int(min_consensus_after_loss or 1))
    required_liquidity = max(0.0, float(min_liquidity_after_loss or 0.0))

    if pnl <= -abs(hard):
        return SessionPnlGuardDecision(
            allow_entry=False,
            reason="SESSION_HARD_LOSS_HALT",
            session_pnl_usdc=round(pnl, 8),
            soft_loss_usdc=round(soft, 8),
            hard_loss_usdc=round(hard, 8),
            required_edge_bps=round(required_edge, 8),
            required_consensus_wallets=required_consensus,
            required_liquidity_score=round(required_liquidity, 8),
            protection_mode=True,
        )

    if pnl <= -abs(soft):
        if edge < required_edge:
            return _blocked(
                "SESSION_LOSS_REQUIRES_STRONGER_EDGE",
                pnl,
                soft,
                hard,
                required_edge,
                required_consensus,
                required_liquidity,
            )
        if consensus < required_consensus:
            return _blocked(
                "SESSION_LOSS_REQUIRES_CLUSTER_CONSENSUS",
                pnl,
                soft,
                hard,
                required_edge,
                required_consensus,
                required_liquidity,
            )
        if liquidity < required_liquidity:
            return _blocked(
                "SESSION_LOSS_REQUIRES_HIGHER_LIQUIDITY",
                pnl,
                soft,
                hard,
                required_edge,
                required_consensus,
                required_liquidity,
            )

    return SessionPnlGuardDecision(
        allow_entry=True,
        reason="SESSION_PNL_GUARD_OK",
        session_pnl_usdc=round(pnl, 8),
        soft_loss_usdc=round(soft, 8),
        hard_loss_usdc=round(hard, 8),
        required_edge_bps=round(required_edge, 8),
        required_consensus_wallets=required_consensus,
        required_liquidity_score=round(required_liquidity, 8),
        protection_mode=False,
    )


def _blocked(
    reason: str,
    pnl: float,
    soft: float,
    hard: float,
    required_edge: float,
    required_consensus: int,
    required_liquidity: float,
) -> SessionPnlGuardDecision:
    return SessionPnlGuardDecision(
        allow_entry=False,
        reason=reason,
        session_pnl_usdc=round(pnl, 8),
        soft_loss_usdc=round(soft, 8),
        hard_loss_usdc=round(hard, 8),
        required_edge_bps=round(required_edge, 8),
        required_consensus_wallets=required_consensus,
        required_liquidity_score=round(required_liquidity, 8),
        protection_mode=True,
    )


__all__ = ["SessionPnlGuardDecision", "evaluate_session_pnl_guard"]
