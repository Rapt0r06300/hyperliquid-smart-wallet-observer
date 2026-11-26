from pathlib import Path

from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import LeaderboardWalletCandidate
from hl_observer.wallets.leaderboard_queries import latest_leaderboard_candidate_rows


def test_latest_unique_pool_does_not_let_reimports_crowd_out_wallets(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'leaderboard_queries.sqlite3'}"
    init_db(db_url)
    session_factory = create_session_factory(create_sqlite_engine(db_url))
    first = "0x" + "a" * 40
    second = "0x" + "b" * 40
    with session_factory() as session:
        session.add_all(
            [
                LeaderboardWalletCandidate(wallet_address=first, period="30D", pnl_usdc=10),
                LeaderboardWalletCandidate(wallet_address=second, period="30D", pnl_usdc=20),
                LeaderboardWalletCandidate(wallet_address=first.upper().replace("0X", "0x"), period="30D", pnl_usdc=30),
                LeaderboardWalletCandidate(wallet_address=first, period="30D", pnl_usdc=40),
            ]
        )
        session.flush()

        rows = latest_leaderboard_candidate_rows(session, limit=2)

    assert len(rows) == 2
    assert {row.wallet_address.lower() for row in rows} == {first, second}
    latest_first = next(row for row in rows if row.wallet_address.lower() == first)
    assert latest_first.pnl_usdc == 40


def test_latest_pool_applies_period_and_metrics_to_current_rows(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'leaderboard_period.sqlite3'}"
    init_db(db_url)
    session_factory = create_session_factory(create_sqlite_engine(db_url))
    address = "0x" + "c" * 40
    with session_factory() as session:
        session.add_all(
            [
                LeaderboardWalletCandidate(wallet_address=address, period="30D", pnl_usdc=500),
                LeaderboardWalletCandidate(wallet_address=address, period="30D", pnl_usdc=-1),
                LeaderboardWalletCandidate(wallet_address=address, period="7D", pnl_usdc=5),
            ]
        )
        session.flush()

        filtered = latest_leaderboard_candidate_rows(session, limit=10, period="30D", min_pnl=0)
        current_period = latest_leaderboard_candidate_rows(session, limit=10, period="7D", min_pnl=0)

    assert filtered == []
    assert len(current_period) == 1
    assert current_period[0].period == "7D"
