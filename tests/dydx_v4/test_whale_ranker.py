from __future__ import annotations

from types import SimpleNamespace

from hyper_smart_observer.dydx_v4.whale_ranker import blended_whale_top, whale_score, whale_stats


class Index:
    def __init__(self, wallets):
        self._wallets = wallets

    def all(self):
        return list(self._wallets)


def test_whale_score_prefers_large_pnl_and_balance() -> None:
    small = SimpleNamespace(address="dydx1small", net_pnl_usdc=100, usdc_balance=1000, activity_count=2, profit_factor=1.0, winrate=0.4)
    large = SimpleNamespace(address="dydx1large", net_pnl_usdc=500000, usdc_balance=1000000, activity_count=50, profit_factor=2.0, winrate=0.6)

    assert whale_score(large) > whale_score(small)


def test_blended_whale_top_keeps_whales_first() -> None:
    whale = SimpleNamespace(address="dydx1whale", net_pnl_usdc=900000, usdc_balance=500000, activity_count=20, score=1)
    general = SimpleNamespace(address="dydx1general", net_pnl_usdc=0, usdc_balance=0, activity_count=2, score=99)
    out = blended_whale_top(Index([general, whale]), limit=2, whale_share=0.5)

    assert out[0][0] == "dydx1whale"
    assert {addr for addr, _ in out} == {"dydx1whale", "dydx1general"}


def test_whale_stats_reports_counts() -> None:
    wallets = [SimpleNamespace(address="dydx1a", net_pnl_usdc=900000, usdc_balance=500000, activity_count=20)]
    stats = whale_stats(Index(wallets))

    assert stats["whale_candidates"] >= 1
    assert stats["max_whale_score"] > 0
    assert stats["top_pnl_usdc"] == 900000
