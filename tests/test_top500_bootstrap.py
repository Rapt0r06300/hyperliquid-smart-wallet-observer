from pathlib import Path

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import LeaderboardWalletCandidate
from hl_observer.wallets.top500_bootstrap import bootstrap_top_wallets


def test_bootstrap_prioritizes_leaderboard_source(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'top500.sqlite3'}"
    init_db(settings.database_url)
    factory = create_session_factory(create_sqlite_engine(settings.database_url))
    with factory() as session:
        session.add(
            LeaderboardWalletCandidate(
                wallet_address="0x" + "e" * 40,
                rank=1,
                period="30D",
                account_value_usdc=1_000_000,
                pnl_usdc=100_000,
                roi_pct=50,
                volume_usdc=10_000_000,
                leaderboard_score=95,
                selected_for_revalidation=True,
                selected_for_backfill=True,
                source_confidence=90,
            )
        )
        result = bootstrap_top_wallets(settings, session=session, target=500, dry_run=True)

    assert result.wallets_selected == 1
    assert result.status == "INCOMPLETE"


def test_bootstrap_never_invents_wallets(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'top500_empty.sqlite3'}"
    init_db(settings.database_url)
    factory = create_session_factory(create_sqlite_engine(settings.database_url))
    with factory() as session:
        result = bootstrap_top_wallets(settings, session=session, target=500, dry_run=True)

    assert result.wallets_selected == 0
    assert result.selected_wallets == []


def test_bootstrap_ignores_stale_rank_biased_persisted_scores(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'top500_recalculated.sqlite3'}"
    init_db(settings.database_url)
    factory = create_session_factory(create_sqlite_engine(settings.database_url))
    stale_high = "0x" + "1" * 40
    evidence_high = "0x" + "2" * 40
    with factory() as session:
        session.add_all([
            LeaderboardWalletCandidate(
                wallet_address=stale_high,
                rank=1,
                period="30D",
                account_value_usdc=0,
                pnl_usdc=-100_000,
                roi_pct=-50,
                volume_usdc=0,
                source_confidence=0,
                leaderboard_score=100,
            ),
            LeaderboardWalletCandidate(
                wallet_address=evidence_high,
                rank=500,
                period="30D",
                account_value_usdc=1_000_000,
                pnl_usdc=100_000,
                roi_pct=50,
                volume_usdc=10_000_000,
                source_confidence=95,
                leaderboard_score=0,
            ),
        ])
        result = bootstrap_top_wallets(settings, session=session, target=1, dry_run=True)

    assert result.wallets_selected == 1
    assert result.selected_wallets[0].wallet_address == evidence_high
