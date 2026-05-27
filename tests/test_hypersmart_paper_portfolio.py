from datetime import UTC, datetime

from hyper_smart_observer.hyperliquid_client.models import PaperTrade, PaperTradeStatus
from hyper_smart_observer.paper_trading.portfolio import PaperPortfolio


def test_hypersmart_paper_portfolio_snapshot():
    portfolio = PaperPortfolio(starting_equity=1000.0, cash_usdc=1000.0)
    portfolio.trades.append(
        PaperTrade(
            trade_id="t1",
            signal_id="s1",
            coin="ETH",
            side="BUY",
            entry_price=100.0,
            size=1.0,
            simulated_fee=0.1,
            simulated_slippage=0.0,
            opened_at=datetime.now(UTC),
            net_pnl=5.0,
            fee_entry=0.1,
            fee_exit=0.1,
            status=PaperTradeStatus.CLOSED,
            state="CLOSED",
        )
    )

    snapshot = portfolio.snapshot()

    assert snapshot.current_equity == 1005.0
    assert snapshot.realized_pnl == 5.0
    assert snapshot.total_fees == 0.2
