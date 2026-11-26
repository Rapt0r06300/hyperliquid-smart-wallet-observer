from pathlib import Path

from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import LeaderboardWalletCandidate, Wallet
from hl_observer.wallets.discovery_filters import dedupe_candidates
from hl_observer.wallets.discovery_sources import (
    ConfigWalletSource,
    HyperliquidLeaderboardSource,
    LocalDbWalletSource,
    PublicTradesWalletSource,
    WalletDiscoveryCandidate,
    build_discovery_sources,
)

VALID_WALLET = "0x" + "7" * 40


def test_discovery_local_db_source_returns_wallets(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'sources.sqlite3'}"
    init_db(db_url)
    session_factory = create_session_factory(create_sqlite_engine(db_url))
    with session_factory() as session:
        session.add(Wallet(address=VALID_WALLET, label="test", status="observed"))
        session.commit()
        result = LocalDbWalletSource().fetch_candidates(session=session)

    assert result.status == "ok"
    assert result.candidates[0].address == VALID_WALLET


def test_discovery_config_source_returns_wallets(tmp_path: Path):
    path = tmp_path / "wallets.yaml"
    path.write_text(
        f"wallets:\n  watchlist:\n    - address: {VALID_WALLET}\n      label: local\n",
        encoding="utf-8",
    )

    result = ConfigWalletSource(path).fetch_candidates()

    assert result.status == "ok"
    assert result.candidates[0].address == VALID_WALLET


def test_leaderboard_discovery_uses_recalculated_evidence_score(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'leaderboard_source.sqlite3'}"
    init_db(db_url)
    session_factory = create_session_factory(create_sqlite_engine(db_url))
    stale_high = "0x" + "3" * 40
    evidence_high = "0x" + "4" * 40
    with session_factory() as session:
        session.add_all([
            LeaderboardWalletCandidate(
                wallet_address=stale_high, rank=1, period="30D",
                account_value_usdc=0, pnl_usdc=-100_000, roi_pct=-50,
                volume_usdc=0, source_confidence=0, leaderboard_score=100,
            ),
            LeaderboardWalletCandidate(
                wallet_address=evidence_high, rank=500, period="30D",
                account_value_usdc=1_000_000, pnl_usdc=100_000, roi_pct=50,
                volume_usdc=10_000_000, source_confidence=95, leaderboard_score=0,
            ),
        ])
        session.flush()
        result = HyperliquidLeaderboardSource().fetch_candidates(session=session, limit=10)

    assert result.status == "ok"
    assert result.candidates[0].address == evidence_high
    assert result.candidates[0].raw_payload["leaderboard_score"] > result.candidates[1].raw_payload["leaderboard_score"]


def test_public_trade_discovery_is_in_default_sources():
    sources = build_discovery_sources(["all"])

    assert any(isinstance(source, PublicTradesWalletSource) for source in sources)


def test_deduplication_merges_only_verified_public_activity_without_replacing_leaderboard():
    leaderboard = WalletDiscoveryCandidate(
        address=VALID_WALLET,
        source_name="hyperliquid_leaderboard",
        source_type="official_leaderboard",
        external_pnl_usdc=123.0,
        confidence_score=0.9,
    )
    public_trade = WalletDiscoveryCandidate(
        address=VALID_WALLET.upper().replace("0X", "0x"),
        source_name="public_trades_ws",
        source_type="websocket_read_only",
        activity_evidence_verified=True,
        activity_trade_count=12,
        activity_window_start_ms=1_700_000_000_000,
        activity_window_end_ms=1_700_000_045_000,
        last_trade_event_ms=1_700_000_040_000,
        raw_payload={"run_id": 12},
        confidence_score=0.85,
    )

    unique, rejected = dedupe_candidates([leaderboard, public_trade])

    assert len(unique) == 1
    assert unique[0].source_name == "hyperliquid_leaderboard"
    assert unique[0].external_pnl_usdc == 123.0
    assert unique[0].activity_evidence_verified is True
    assert unique[0].activity_trade_count == 12
    assert unique[0].raw_payload["public_trade_activity"]["run_id"] == 12
    assert rejected[public_trade.address].value == "REJECT_DUPLICATE"
