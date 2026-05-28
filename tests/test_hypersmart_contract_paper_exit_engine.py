import pytest
from pathlib import Path
from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from hyper_smart_observer.hyperliquid_client.models import PaperIntentStatus, PaperTradeStatus

def test_paper_exit_on_leader_close(tmp_path):
    config = AppConfig(
        runtime_root=tmp_path,
        database_path=tmp_path / "paper_test.sqlite3",
        paper_starting_equity=1000.0
    )
    simulator = PaperTradingSimulator(config)

    # We need a scored wallet to pass risk gates if required, but let's assume we can open one
    # Or mock the risk engine. For this contract test, we verify the close_paper_trade method.

    # Manually insert a trade to close
    from hyper_smart_observer.storage.database import initialize_database, get_connection
    from hyper_smart_observer.storage.repositories import paper_trades_repo
    from hyper_smart_observer.hyperliquid_client.models import PaperTrade
    from datetime import datetime, UTC

    initialize_database(config)
    trade = PaperTrade(
        trade_id="test_trade_123",
        signal_id="sig_123",
        intent_id="int_123",
        wallet_address="0x1111111111111111111111111111111111111111",
        coin="BTC",
        side="BUY",
        entry_price=60000.0,
        size=0.001,
        notional=60.0,
        simulated_fee=0.03,
        simulated_slippage=0.03,
        opened_at=datetime.now(UTC),
        status=PaperTradeStatus.OPEN
    )

    with get_connection(config) as conn:
        paper_trades_repo.insert_paper_trade(conn, trade)
        conn.commit()

    result = simulator.close_paper_trade("test_trade_123", 65000.0, "leader_closed")

    assert result.success is True
    assert result.net_pnl > 4.0 # 5000 * 0.001 = 5.0 minus fees

    report = simulator.generate_report()
    assert report["starting_equity"] == 1000.0
    assert report["closed_trades"] == 1
