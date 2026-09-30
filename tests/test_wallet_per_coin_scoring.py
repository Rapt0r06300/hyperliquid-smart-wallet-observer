from __future__ import annotations

from pathlib import Path

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import WalletCoinProfileModel, WalletCoinScoreModel
from hl_observer.storage.repositories import CollectionRepository
from hl_observer.wallets.per_coin_scoring import score_wallet_coin
from hl_observer.wallets.wallet_coin_profile import build_wallet_coin_profiles

VALID_WALLET = "0x" + "2" * 40


def test_wallet_coin_profile_created():
    profiles = build_wallet_coin_profiles(
        VALID_WALLET,
        [
            {"coin": "SOL", "time": 1, "px": "20", "sz": "10", "closedPnl": "12"},
            {"coin": "SOL", "time": 2, "px": "21", "sz": "10", "closedPnl": "8"},
            {"coin": "HYPE", "time": 3, "px": "5", "sz": "10", "closedPnl": "2"},
        ],
        min_fills_for_score=2,
    )

    assert {profile.coin for profile in profiles} == {"SOL", "HYPE"}
    assert next(profile for profile in profiles if profile.coin == "SOL").estimated_pnl_usdc == 20


def test_wallet_coin_score_created(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'wallet_coin.sqlite3'}"
    init_db(settings.database_url)
    session_factory = create_session_factory(create_sqlite_engine(settings.database_url))
    profile = build_wallet_coin_profiles(
        VALID_WALLET,
        [
            {"coin": "SOL", "time": 1, "px": "20", "sz": "10", "closedPnl": "12"},
            {"coin": "SOL", "time": 2, "px": "21", "sz": "10", "closedPnl": "8"},
            {"coin": "SOL", "time": 3, "px": "22", "sz": "10", "closedPnl": "6"},
        ],
        liquidity_by_coin={"SOL": 80},
        min_fills_for_score=3,
    )[0]
    score = score_wallet_coin(profile)

    with session_factory() as session:
        repo = CollectionRepository(session)
        repo.store_wallet_coin_profile(profile)
        repo.store_wallet_coin_score(score)
        session.commit()
        assert session.query(WalletCoinProfileModel).count() == 1
        assert session.query(WalletCoinScoreModel).count() == 1


def test_discover_wallets_keeps_altcoin_positive_wallet():
    profile = build_wallet_coin_profiles(
        VALID_WALLET,
        [
            {"coin": "HYPE", "time": 1, "px": "5", "sz": "100", "closedPnl": "30"},
            {"coin": "HYPE", "time": 2, "px": "6", "sz": "100", "closedPnl": "20"},
            {"coin": "HYPE", "time": 3, "px": "7", "sz": "100", "closedPnl": "10"},
        ],
        liquidity_by_coin={"HYPE": 90},
        min_fills_for_score=3,
    )[0]

    score = score_wallet_coin(profile)

    assert profile.coin == "HYPE"
    assert score.final_score > 0
    assert "not_enough_coin_fills" not in score.reasons

