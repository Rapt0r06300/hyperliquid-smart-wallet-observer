from pathlib import Path

from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import LeaderboardWalletCandidate
from hl_observer.wallets.leaderboard_import import import_leaderboard_file


VALID = "0x" + "c" * 40


def test_leaderboard_import_accepts_full_addresses(tmp_path: Path):
    path = tmp_path / "leaderboard.csv"
    path.write_text("rank,address,pnl,roi\n1,%s,100,10\n" % VALID, encoding="utf-8")

    result = import_leaderboard_file(path)

    assert result.candidates_created == 1
    assert result.candidates[0].wallet_address == VALID


def test_leaderboard_import_rejects_truncated_addresses(tmp_path: Path):
    path = tmp_path / "leaderboard.txt"
    path.write_text("0x393d...2109\n", encoding="utf-8")

    result = import_leaderboard_file(path)

    assert result.truncated_addresses_seen == 1
    assert result.candidates_created == 0


def test_leaderboard_import_stores_candidates(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'leaderboard.sqlite3'}"
    init_db(db_url)
    factory = create_session_factory(create_sqlite_engine(db_url))
    path = tmp_path / "leaderboard.csv"
    path.write_text("rank,address,pnl,roi\n1,%s,100,10\n" % VALID, encoding="utf-8")

    with factory() as session:
        import_leaderboard_file(path, store=True, session=session)
        session.commit()
        assert session.query(LeaderboardWalletCandidate).count() == 1
