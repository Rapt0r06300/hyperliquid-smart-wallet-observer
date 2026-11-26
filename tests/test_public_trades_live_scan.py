import json

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.config.loader import load_settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import MarketSnapshot, SourceHealth, TopWallet, WalletCandidateModel
from hl_observer.utils.time import now_ms
from hl_observer.wallets.public_trades_live import (
    ingest_public_trade_messages,
    normalize_coin_list,
    store_public_trade_scan,
    trade_payloads_from_message,
)

WALLET_A = "0x" + "a" * 40
WALLET_B = "0x" + "b" * 40


def _trade_message(coin="BTC", px="100", sz="2", event_time=1_700_000_000_000):
    return json.dumps(
        {
            "channel": "trades",
            "data": [
                {
                    "coin": coin,
                    "side": "B",
                    "px": px,
                    "sz": sz,
                    "hash": "0xhash",
                    "time": event_time,
                    "tid": 123,
                    "users": [WALLET_A, WALLET_B],
                }
            ],
        }
    )


def test_public_trades_parser_extracts_ws_trades_users():
    trades = trade_payloads_from_message(_trade_message())

    assert len(trades) == 1
    assert trades[0]["users"] == [WALLET_A, WALLET_B]


def test_public_trade_coin_normalization_skips_invalid_hash_markets():
    coins = normalize_coin_list(["BTC", "#1000", "ETH", "bad coin"])

    assert coins == ["BTC", "ETH"]


def test_public_trades_scan_discovers_wallets_without_info_api():
    result = ingest_public_trade_messages([_trade_message(), _trade_message(coin="ETH", px="200", sz="1")])

    assert result.trades_seen == 2
    assert len(result.wallet_stats) == 2
    assert result.wallet_stats[WALLET_A.lower()].observed_notional_usdc == 400
    assert result.wallet_stats[WALLET_A.lower()].coins == {"BTC", "ETH"}


def test_public_trades_without_exchange_timestamp_are_not_counted_as_fresh_activity():
    trade = json.loads(_trade_message())["data"][0]
    trade.pop("time")
    result = ingest_public_trade_messages([json.dumps({"channel": "trades", "data": [trade]})])

    assert result.trades_seen == 1
    assert not result.wallet_stats
    assert "trade_event_timestamp_missing_or_invalid" in result.warnings


def test_public_trades_reject_nonintegral_or_boolean_exchange_timestamps():
    for event_time in (1_700_000_000_000.5, True):
        trade = json.loads(_trade_message(event_time=event_time))["data"][0]
        result = ingest_public_trade_messages([json.dumps({"channel": "trades", "data": [trade]})])

        assert not result.wallet_stats
        assert "trade_event_timestamp_missing_or_invalid" in result.warnings


def test_public_trades_scan_stores_candidates_and_top_wallets(tmp_path):
    db = tmp_path / "live.sqlite3"
    init_db(f"sqlite:///{db}")
    session_factory = create_session_factory(create_sqlite_engine(f"sqlite:///{db}"))
    result = ingest_public_trade_messages([_trade_message()], max_wallets=10)

    with session_factory() as session:
        store_public_trade_scan(session, result, promote_top=2)
        session.commit()
        assert session.query(WalletCandidateModel).count() == 2
        assert session.query(TopWallet).count() == 2
        top = session.query(TopWallet).first()
        assert top.source == "public_trades_ws"
        assert "requires_/info_confirmation" in (top.notes or "")
        stored = session.query(WalletCandidateModel).first()
        assert stored.raw_payload_json["activity_timestamps_verified"] is False
        assert stored.raw_payload_json["activity_window_end_ms"] >= stored.raw_payload_json["activity_window_start_ms"]


def test_public_trades_discovery_source_reads_latest_complete_scan(tmp_path):
    from hl_observer.wallets.discovery import WalletDiscoveryPlan, _score_and_select
    from hl_observer.wallets.discovery_sources import PublicTradesWalletSource

    db = tmp_path / "discovery_public_trades.sqlite3"
    init_db(f"sqlite:///{db}")
    session_factory = create_session_factory(create_sqlite_engine(f"sqlite:///{db}"))
    observed_at = now_ms()
    result = ingest_public_trade_messages([_trade_message(event_time=observed_at - 10_000)])
    result.network_read = True
    result.duration_seconds = 45
    result.scan_started_at_ms = observed_at - 45_000
    result.scan_finished_at_ms = observed_at

    with session_factory() as session:
        store_public_trade_scan(session, result, promote_top=2)
        session.commit()
        candidates = PublicTradesWalletSource().fetch_candidates(session=session, limit=10)

    assert candidates.status == "ok"
    assert len(candidates.candidates) == 2
    candidate = candidates.candidates[0]
    assert candidate.activity_evidence_verified is True
    assert candidate.activity_trade_count == 1
    assert candidate.activity_window_end_ms >= candidate.activity_window_start_ms
    assert candidate.last_trade_event_ms == observed_at - 10_000
    assert candidate.external_volume_usdc is None
    scored = _score_and_select(WalletDiscoveryPlan(), candidates.candidates)
    assert scored[0].score.activity_score == 100.0 / 15.0
    assert "exchange_event_recency_measured_not_edge_proof" in scored[0].score.reasons
    complete_run_id = candidate.raw_payload["run_id"]

    partial = ingest_public_trade_messages([_trade_message()])
    partial.stopped_reason = "SOURCE_UNAVAILABLE"
    with session_factory() as session:
        store_public_trade_scan(session, partial, promote_top=2)
        session.commit()
        latest_eligible = PublicTradesWalletSource().fetch_candidates(session=session, limit=10)

    assert all(item.raw_payload["run_id"] == complete_run_id for item in latest_eligible.candidates)


def test_public_trades_scan_updates_promoted_top_wallets_without_duplicate_rows(tmp_path):
    db = tmp_path / "live_upsert.sqlite3"
    init_db(f"sqlite:///{db}")
    session_factory = create_session_factory(create_sqlite_engine(f"sqlite:///{db}"))
    result = ingest_public_trade_messages([_trade_message()], max_wallets=10)

    with session_factory() as session:
        store_public_trade_scan(session, result, promote_top=2)
        store_public_trade_scan(session, result, promote_top=2)
        session.commit()

        assert session.query(TopWallet).count() == 2


def test_public_trades_scan_stores_market_marks_for_live_simulation(tmp_path):
    db = tmp_path / "live_marks.sqlite3"
    init_db(f"sqlite:///{db}")
    session_factory = create_session_factory(create_sqlite_engine(f"sqlite:///{db}"))
    result = ingest_public_trade_messages(
        [
            _trade_message(coin="ETH", px="2010", sz="1"),
            _trade_message(coin="ETH", px="2020", sz="1"),
        ],
        max_wallets=10,
    )

    with session_factory() as session:
        store_public_trade_scan(session, result, promote_top=2)
        session.commit()
        snapshot = session.query(MarketSnapshot).order_by(MarketSnapshot.id.desc()).first()
        health = session.get(SourceHealth, "market_marks_public_trades")

        assert snapshot.source == "publicTradesWS"
        assert snapshot.raw_json["prices"]["ETH"] == 2020.0
        assert health is not None


def test_live_public_scan_cli_requires_explicit_network_read(monkeypatch, tmp_path):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{tmp_path / 'cli.sqlite3'}")
    result = CliRunner().invoke(app, ["live-public-scan", "--duration-seconds", "1", "--dry-run"])

    assert result.exit_code != 0
    assert "--network-read is required" in result.output


def test_default_settings_do_not_enable_execution_for_public_scan(monkeypatch):
    monkeypatch.setenv("HL_ENV", "paper")
    monkeypatch.setenv("HL_ENABLE_MAINNET_EXECUTION", "false")
    monkeypatch.setenv("HL_ENABLE_TESTNET_EXECUTION", "false")
    settings = load_settings()

    assert settings.execution.enable_mainnet_execution is False
    assert settings.execution.enable_testnet_execution is False
