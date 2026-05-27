from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.hyperliquid_client.models import Wallet
from hyper_smart_observer.storage.database import get_connection, initialize_database
from hyper_smart_observer.storage.repositories.wallet_repo import get_wallet, insert_wallet


def test_hypersmart_initialize_sqlite_creates_tables(tmp_path):
    config = AppConfig(database_path=tmp_path / "hypersmart.sqlite3")
    initialize_database(config)

    with get_connection(config) as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }

    assert {"wallets", "fills", "wallet_scores", "signals", "paper_trades", "risk_events"} <= tables


def test_hypersmart_wallet_repository_insert_get(tmp_path):
    config = AppConfig(database_path=tmp_path / "repo.sqlite3")
    initialize_database(config)
    wallet = Wallet(address="0x" + "2" * 40, source="test")

    with get_connection(config) as conn:
        insert_wallet(conn, wallet)
        conn.commit()
        loaded = get_wallet(conn, wallet.address)

    assert loaded is not None
    assert loaded.address == wallet.address
