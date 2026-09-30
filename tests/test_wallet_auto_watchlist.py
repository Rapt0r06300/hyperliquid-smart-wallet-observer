from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import AutoWatchlist
from hl_observer.wallets.auto_watchlist import add_to_auto_watchlist

VALID_WALLET = "0x" + "8" * 40


def test_auto_watchlist_stores_selected_wallet(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'watchlist.sqlite3'}"
    init_db(db_url)
    session_factory = create_session_factory(create_sqlite_engine(db_url))

    with session_factory() as session:
        add_to_auto_watchlist(
            session,
            wallet_address=VALID_WALLET,
            label="candidate",
            source="local_db",
            discovery_score=80,
            notes="selected_for_backfill",
        )
        session.commit()

    with session_factory() as session:
        row = session.query(AutoWatchlist).one()

    assert row.wallet_address == VALID_WALLET
    assert row.discovery_score == 80
    assert row.status == "selected"
