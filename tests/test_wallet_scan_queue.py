from pathlib import Path

from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import TopWallet, WalletScanQueue
from hl_observer.utils.time import now_ms
from hl_observer.wallets.scan_queue import enqueue_wallets, scan_wallet_queue


VALID = "0x" + "f" * 40


def test_truncated_address_never_enters_scan_queue(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'queue.sqlite3'}"
    init_db(db_url)
    factory = create_session_factory(create_sqlite_engine(db_url))
    with factory() as session:
        result = enqueue_wallets(session, [("0x393d...2109", 99, "leaderboard")], dry_run=False)
        session.commit()
        assert result.skipped == 1
        assert session.query(WalletScanQueue).count() == 0


def test_scan_queue_prioritizes_best_wallets(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'queue_top.sqlite3'}"
    init_db(db_url)
    factory = create_session_factory(create_sqlite_engine(db_url))
    with factory() as session:
        session.add(TopWallet(wallet_address=VALID, rank=1, source="leaderboard", score=99, selected_at_ms=now_ms()))
        result = scan_wallet_queue(session, max_wallets=500, batch_size=25, dry_run=True)

    assert VALID in result.selected_wallets
