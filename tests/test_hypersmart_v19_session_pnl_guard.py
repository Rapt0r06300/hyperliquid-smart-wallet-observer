from __future__ import annotations

from hl_observer.risk.session_pnl_guard import evaluate_session_pnl_guard


def test_session_pnl_guard_allows_healthy_session() -> None:
    decision = evaluate_session_pnl_guard(
        session_pnl_usdc=0.0,
        starting_equity_usdt=1000.0,
        edge_remaining_bps=16.0,
        min_edge_required_bps=15.0,
        consensus_wallets=1,
        liquidity_score=0.25,
    )

    assert decision.allow_entry is True
    assert decision.reason == "SESSION_PNL_GUARD_OK"
    assert decision.protection_mode is False


def test_session_pnl_guard_blocks_weak_signal_after_loss() -> None:
    decision = evaluate_session_pnl_guard(
        session_pnl_usdc=-0.33,
        starting_equity_usdt=1000.0,
        edge_remaining_bps=18.0,
        min_edge_required_bps=15.0,
        consensus_wallets=3,
        liquidity_score=0.8,
    )

    assert decision.allow_entry is False
    assert decision.reason == "SESSION_LOSS_REQUIRES_STRONGER_EDGE"
    assert decision.protection_mode is True


def test_session_pnl_guard_allows_high_conviction_signal_after_small_loss() -> None:
    decision = evaluate_session_pnl_guard(
        session_pnl_usdc=-0.33,
        starting_equity_usdt=1000.0,
        edge_remaining_bps=31.0,
        min_edge_required_bps=15.0,
        consensus_wallets=4,
        liquidity_score=0.7,
    )

    assert decision.allow_entry is True
    assert decision.reason == "SESSION_PNL_GUARD_OK"


def test_session_pnl_guard_hard_halt_blocks_even_strong_signal() -> None:
    decision = evaluate_session_pnl_guard(
        session_pnl_usdc=-7.5,
        starting_equity_usdt=1000.0,
        edge_remaining_bps=80.0,
        min_edge_required_bps=15.0,
        consensus_wallets=8,
        liquidity_score=1.0,
    )

    assert decision.allow_entry is False
    assert decision.reason == "SESSION_HARD_LOSS_HALT"
