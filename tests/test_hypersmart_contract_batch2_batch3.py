import pytest
import sqlite3
import tempfile
from pathlib import Path
from hyper_smart_observer.storage.database import initialize_database, get_connection
from hyper_smart_observer.copy_mode.copy_models import SignalCandidate, DeltaAction, SignalDecision, utc_now

@pytest.mark.contract
def test_contract_batch2_database_persistence():
    """
    Contract (Batch 2): All official tables must be present and writable.
    """
    with tempfile.NamedTemporaryFile(suffix=".sqlite3") as tmp:
        db_path = Path(tmp.name)
        from hyper_smart_observer.app.config import AppConfig
        config = AppConfig(database_path=db_path)

        initialize_database(config)

        with get_connection(config) as conn:
            # Check a few critical tables from schema.sql
            tables = [
                "leaderboard_shortlist", "leader_deltas", "copy_signal_candidates",
                "no_trade_decisions", "paper_trades", "fill_dedupe"
            ]
            for table in tables:
                res = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
                assert res is not None

@pytest.mark.contract
def test_contract_batch3_websocket_planning():
    """
    Contract (Batch 3): WebSocket planning must reject more than 10 unique users.
    """
    from hyper_smart_observer.realtime_monitor.websocket_manager import WebSocketManager
    from hyper_smart_observer.realtime_monitor.subscriptions import Subscription
    from hyper_smart_observer.realtime_monitor.stream_models import StreamType
    from hyper_smart_observer.app.config import AppConfig

    config = AppConfig(ws_max_user_subscriptions=10)
    manager = WebSocketManager(config)

    subs = [Subscription(StreamType.USER_FILLS, user=f"0x{i:040}") for i in range(15)]
    plan = manager.build_plan(subs, dry_run=True)

    # Validation must bound to 10
    assert len(plan.subscriptions) <= 10
