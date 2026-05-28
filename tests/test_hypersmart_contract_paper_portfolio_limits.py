import pytest
from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from hyper_smart_observer.hyperliquid_client.models import PaperIntent

def test_paper_portfolio_total_exposure_limit(tmp_path):
    # Total exposure cap = 200
    config = AppConfig(
        runtime_root=tmp_path,
        database_path=tmp_path / "paper_limit_test.sqlite3",
        paper_max_total_exposure=200.0,
        paper_max_position_notional=100.0
    )
    simulator = PaperTradingSimulator(config)

    # Mock portfolio with 180 notional
    from hyper_smart_observer.storage.database import initialize_database, get_connection
    from hyper_smart_observer.storage.repositories import paper_trades_repo
    from hyper_smart_observer.hyperliquid_client.models import PaperTrade, PaperTradeStatus
    from datetime import datetime, UTC

    initialize_database(config)

    # Insert 180 notional
    trade = PaperTrade(
        trade_id="t1", signal_id="s1", intent_id="i1", coin="BTC", side="BUY",
        entry_price=60000.0, size=0.003, notional=180.0,
        simulated_fee=0.0, simulated_slippage=0.0, opened_at=datetime.now(UTC),
        status=PaperTradeStatus.OPEN
    )
    with get_connection(config) as conn:
        paper_trades_repo.insert_paper_trade(conn, trade)
        conn.commit()

    # Attempt to open 50 more (Total 230 > 200)
    intent = simulator.create_intent_from_wallet_score(
        "0x1111111111111111111111111111111111111111",
        "ETH", "BUY", 3000.0, 50.0
    )

    decision = simulator.evaluate_intent(intent)
    assert decision.allowed is False
    assert decision.reason_code == "MAX_TOTAL_EXPOSURE_REACHED"
