from __future__ import annotations

import inspect

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.config.loader import load_settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import (
    AutoWatchlist,
    Wallet,
    WalletCandidateModel,
    WalletDiscoverySourceModel,
)
from hl_observer.wallets import discovery as discovery_module
from hl_observer.wallets.discovery import WalletDiscoveryPlan, run_wallet_discovery
from hl_observer.wallets.discovery_sources import (
    WalletDiscoveryCandidate,
    WalletDiscoverySource,
    WalletDiscoverySourceResult,
)

VALID_WALLET = "0x" + "9" * 40


def _settings(tmp_path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'discovery.sqlite3'}"
    return settings


def _session_factory(db_url):
    init_db(db_url)
    return create_session_factory(create_sqlite_engine(db_url))


def test_discover_wallets_command_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{tmp_path / 'cli.sqlite3'}")
    result = CliRunner().invoke(app, ["discover-wallets", "--dry-run", "--report"])

    assert result.exit_code == 0, result.output
    assert "wallet discovery report" in result.output


def test_discovery_rejects_invalid_wallet_address(tmp_path, monkeypatch):
    class CandidateSource(WalletDiscoverySource):
        name = "candidate"
        source_type = "test"
        reliability_score = 0.8

        def fetch_candidates(self, *, session=None, limit=50):
            return WalletDiscoverySourceResult(
                source_name=self.name,
                source_type=self.source_type,
                reliability_score=self.reliability_score,
                status="ok",
                candidates=[
                    WalletDiscoveryCandidate(
                        address="0x123",
                        source_name=self.name,
                        source_type=self.source_type,
                        confidence_score=0.8,
                    )
                ],
            )

    monkeypatch.setattr(discovery_module, "build_discovery_sources", lambda _sources: [CandidateSource()])
    result = run_wallet_discovery(
        WalletDiscoveryPlan(sources=["config"], dry_run=True),
        _settings(tmp_path),
    )

    assert any(item["decision"] == "REJECT_INVALID_ADDRESS" for item in result.rejected)


def test_discovery_deduplicates_wallets(tmp_path, monkeypatch):
    settings = _settings(tmp_path)

    class DuplicateSource(WalletDiscoverySource):
        name = "dupe"
        source_type = "test"
        reliability_score = 0.8

        def fetch_candidates(self, *, session=None, limit=50):
            return WalletDiscoverySourceResult(
                source_name=self.name,
                source_type=self.source_type,
                reliability_score=self.reliability_score,
                status="ok",
                candidates=[
                    WalletDiscoveryCandidate(address=VALID_WALLET, source_name=self.name, source_type=self.source_type, confidence_score=0.8),
                    WalletDiscoveryCandidate(address=VALID_WALLET, source_name=self.name, source_type=self.source_type, confidence_score=0.8),
                ],
            )

    monkeypatch.setattr(discovery_module, "build_discovery_sources", lambda _sources: [DuplicateSource()])

    result = run_wallet_discovery(
        WalletDiscoveryPlan(sources=["local_db"], dry_run=True),
        settings,
    )

    assert result.candidates_found >= 1
    assert result.candidates_after_filter == 1


def test_discovery_selects_top_wallets_for_backfill(tmp_path):
    settings = _settings(tmp_path)
    session_factory = _session_factory(settings.database_url)
    with session_factory() as session:
        session.add(Wallet(address=VALID_WALLET, label=None, status="observed"))
        session.commit()

    result = run_wallet_discovery(
        WalletDiscoveryPlan(sources=["local_db"], dry_run=True, min_discovery_score=50),
        settings,
        session_factory=session_factory,
    )

    assert result.selected_wallets


def test_discovery_stores_candidates(tmp_path):
    settings = _settings(tmp_path)
    session_factory = _session_factory(settings.database_url)
    with session_factory() as session:
        session.add(Wallet(address=VALID_WALLET, label=None, status="observed"))
        session.commit()

    run_wallet_discovery(
        WalletDiscoveryPlan(sources=["local_db"], dry_run=False, store=True, min_discovery_score=50),
        settings,
        session_factory=session_factory,
    )

    with session_factory() as session:
        assert session.query(WalletCandidateModel).count() == 1
        assert session.query(AutoWatchlist).count() == 1


def test_discovery_stores_source_status(tmp_path):
    settings = _settings(tmp_path)
    session_factory = _session_factory(settings.database_url)

    run_wallet_discovery(
        WalletDiscoveryPlan(sources=["hypertracker"], dry_run=False, store=True),
        settings,
        session_factory=session_factory,
    )

    with session_factory() as session:
        source = session.query(WalletDiscoverySourceModel).one()

    assert source.status == "not_implemented"


def test_discovery_handles_source_failure_without_crash(tmp_path, monkeypatch):
    class FailingSource(WalletDiscoverySource):
        name = "failing"
        source_type = "test"
        reliability_score = 0.5

        def fetch_candidates(self, *, session=None, limit=50):
            return WalletDiscoverySourceResult(
                source_name=self.name,
                source_type=self.source_type,
                reliability_score=self.reliability_score,
                status="source_failed",
                error_message="boom",
            )

    monkeypatch.setattr(discovery_module, "build_discovery_sources", lambda _sources: [FailingSource()])
    result = run_wallet_discovery(WalletDiscoveryPlan(dry_run=True), _settings(tmp_path))

    assert result.errors_count == 1
    assert result.state == "no_candidates"


def test_discovery_never_calls_exchange():
    source = inspect.getsource(discovery_module)

    assert "/exchange" not in source


def test_discovery_does_not_require_private_key(tmp_path, monkeypatch):
    monkeypatch.delenv("HL_TESTNET_PRIVATE_KEY", raising=False)
    settings = _settings(tmp_path)

    result = run_wallet_discovery(WalletDiscoveryPlan(sources=["local_db"], dry_run=True), settings)

    assert result.errors_count == 0


def test_discover_wallets_groups_candidates_by_coin(tmp_path, monkeypatch):
    class AltcoinSource(WalletDiscoverySource):
        name = "altcoin"
        source_type = "test"
        reliability_score = 0.9

        def fetch_candidates(self, *, session=None, limit=50):
            return WalletDiscoverySourceResult(
                source_name=self.name,
                source_type=self.source_type,
                reliability_score=self.reliability_score,
                status="ok",
                candidates=[
                    WalletDiscoveryCandidate(
                        address=VALID_WALLET,
                        coin="HYPE",
                        source_name=self.name,
                        source_type=self.source_type,
                        external_pnl_usdc=1000,
                        external_roi_pct=20,
                        confidence_score=0.9,
                    )
                ],
            )

    monkeypatch.setattr(discovery_module, "build_discovery_sources", lambda _sources: [AltcoinSource()])

    result = run_wallet_discovery(
        WalletDiscoveryPlan(sources=["altcoin"], dry_run=True, min_discovery_score=50, include_altcoins=True),
        _settings(tmp_path),
    )

    assert result.selected_wallets
    assert result.selected_by_coin == {"HYPE": 1}
    assert result.selected_wallets[0].candidate.coin == "HYPE"
