from hl_observer.simulation.session_memory import (
    coin_side_session_stats,
    evaluate_coin_side_session_memory,
)


def test_coin_side_session_memory_blocks_same_losing_direction_only():
    events = [
        {
            "status": "LOCAL_REPLAY",
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "coin": "HYPE",
            "leader_side": "SHORT",
            "estimated_net_pnl_usdc": -0.22,
        },
        {
            "status": "LOCAL_REPLAY",
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "coin": "HYPE",
            "leader_side": "SHORT",
            "estimated_net_pnl_usdc": -0.18,
        },
    ]

    blocked = evaluate_coin_side_session_memory(
        events=events,
        coin="HYPE",
        side="SHORT",
        edge_remaining_bps=45.0,
        min_edge_required_bps=22.0,
        consensus_wallets=2,
        liquidity_score=0.4,
        starting_equity_usdt=1000.0,
        cooldown_usdc=0.20,
    )
    opposite_side = evaluate_coin_side_session_memory(
        events=events,
        coin="HYPE",
        side="LONG",
        edge_remaining_bps=45.0,
        min_edge_required_bps=22.0,
        consensus_wallets=2,
        liquidity_score=0.4,
        starting_equity_usdt=1000.0,
        cooldown_usdc=0.20,
    )

    assert not blocked.allow_entry
    assert blocked.reason == "COIN_SIDE_RECENT_LOSS_STREAK_REQUIRES_STRONGER_EDGE"
    assert blocked.stats.recent_loss_streak == 2
    assert opposite_side.allow_entry


def test_coin_side_session_memory_allows_strong_recovery_signal():
    events = [
        {
            "status": "LOCAL_REPLAY",
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "coin": "PURR",
            "leader_side": "LONG",
            "estimated_net_pnl_usdc": -0.35,
        },
        {
            "status": "LOCAL_REPLAY",
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "coin": "PURR",
            "leader_side": "LONG",
            "estimated_net_pnl_usdc": -0.25,
        },
    ]

    decision = evaluate_coin_side_session_memory(
        events=events,
        coin="PURR",
        side="LONG",
        edge_remaining_bps=75.0,
        min_edge_required_bps=22.0,
        consensus_wallets=4,
        liquidity_score=0.8,
        starting_equity_usdt=1000.0,
        cooldown_usdc=0.20,
        extra_edge_after_loss_bps=35.0,
        min_consensus_after_loss=3,
        min_liquidity_after_loss=0.55,
    )

    assert decision.allow_entry
    assert decision.strong_recovery
    assert decision.stats.session_pnl_usdc == -0.6


def test_coin_side_session_stats_uses_local_replay_exits_and_fees():
    events = [
        {
            "status": "LOCAL_REPLAY",
            "bot_replay_action": "PAPER_CONSENSUS_ENTRY_REPLAYED",
            "coin": "BTC",
            "leader_side": "LONG",
            "estimated_net_pnl_usdc": -0.02,
        },
        {
            "status": "LOCAL_REPLAY",
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "coin": "BTC",
            "leader_side": "LONG",
            "estimated_net_pnl_usdc": 0.40,
        },
        {
            "status": "REFUSED",
            "bot_replay_action": "NO_TRADE",
            "coin": "BTC",
            "leader_side": "LONG",
            "estimated_net_pnl_usdc": -999.0,
        },
    ]

    stats = coin_side_session_stats(events, coin="btc", side="long")

    assert stats.session_pnl_usdc == 0.38
    assert stats.realized_exit_pnl_usdc == 0.4
    assert stats.win_count == 1
    assert stats.recent_win_streak == 1
