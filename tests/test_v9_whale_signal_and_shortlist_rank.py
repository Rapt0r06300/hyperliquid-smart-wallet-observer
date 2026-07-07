from hl_observer.signals.whale_fill_signal import (
    WhaleFillConfig,
    build_whale_fill_signal,
)
from hl_observer.scoring.shortlist_rank import (
    WalletStats,
    rank_shortlist,
    smart_money_quality,
)


# ---------- whale fill signal ----------

def test_whale_fresh_large_open_is_primary():
    sig = build_whale_fill_signal(
        action_type="OPEN_LONG", coin="BTC", side="LONG",
        leader_notional_usdc=80_000, fill_age_ms=2_000, leader_score=90, consensus_wallets=2,
    )
    assert sig is not None and sig.is_primary is True
    assert sig.strength > 0.6 and "PRIMARY" in sig.reasons
    assert sig.execution == "forbidden"


def test_whale_exit_returns_none():
    assert build_whale_fill_signal(
        action_type="REDUCE", coin="BTC", side="LONG",
        leader_notional_usdc=80_000, fill_age_ms=1_000, leader_score=90,
    ) is None


def test_whale_stale_returns_none():
    assert build_whale_fill_signal(
        action_type="OPEN_LONG", coin="BTC", side="LONG",
        leader_notional_usdc=80_000, fill_age_ms=120_000, leader_score=90,
    ) is None


def test_whale_too_small_returns_none():
    assert build_whale_fill_signal(
        action_type="OPEN_LONG", coin="BTC", side="LONG",
        leader_notional_usdc=500, fill_age_ms=1_000, leader_score=90,
    ) is None


def test_whale_small_quality_open_is_signal_but_not_primary():
    sig = build_whale_fill_signal(
        action_type="ADD", coin="HYPE", side="LONG",
        leader_notional_usdc=3_000, fill_age_ms=20_000, leader_score=40,
    )
    assert sig is not None and sig.is_primary is False
    assert 0.0 <= sig.strength <= 1.0


# ---------- shortlist ranking ----------

def test_rank_prioritizes_quality_and_activity():
    wallets = [
        WalletStats(address="0xLOW", winrate=0.45, total_pnl_usdc=100, profit_factor=1.0,
                    consistency=0.4, one_big_win_share=0.2, recent_fills=1, last_fill_age_ms=3_000_000),
        WalletStats(address="0xTOP", winrate=0.7, total_pnl_usdc=8_000, profit_factor=2.5,
                    consistency=0.8, one_big_win_share=0.15, recent_fills=18, last_fill_age_ms=60_000),
        WalletStats(address="0xMID", winrate=0.6, total_pnl_usdc=1_500, profit_factor=1.6,
                    consistency=0.6, one_big_win_share=0.25, recent_fills=6, last_fill_age_ms=600_000),
    ]
    ranked = rank_shortlist(wallets)
    assert [r.address for r in ranked][0] == "0xTOP"
    assert ranked[0].rank == 1 and ranked[-1].address == "0xLOW"
    assert "SMART_MONEY" in ranked[0].reasons and "ACTIVE" in ranked[0].reasons


def test_rank_limit_bounds_shortlist():
    wallets = [WalletStats(address=f"0x{i}", winrate=0.6, recent_fills=i) for i in range(10)]
    ranked = rank_shortlist(wallets, limit=3)
    assert len(ranked) == 3 and [r.rank for r in ranked] == [1, 2, 3]


def test_one_big_win_is_penalized_and_flagged():
    spread = WalletStats(address="0xA", winrate=0.6, total_pnl_usdc=3_000, profit_factor=1.8,
                         consistency=0.7, one_big_win_share=0.1, recent_fills=5)
    lucky = WalletStats(address="0xB", winrate=0.6, total_pnl_usdc=3_000, profit_factor=1.8,
                        consistency=0.7, one_big_win_share=0.9, recent_fills=5)
    assert smart_money_quality(spread) > smart_money_quality(lucky)
    ranked = {r.address: r for r in rank_shortlist([spread, lucky])}
    assert "ONE_BIG_WIN_RISK" in ranked["0xB"].reasons
