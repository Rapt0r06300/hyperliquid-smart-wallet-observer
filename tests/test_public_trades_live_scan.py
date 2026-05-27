import json

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.config.loader import load_settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import TopWallet, WalletCandidateModel
from hl_observer.wallets.public_trades_live import (
    ingest_public_trade_messages,
    store_public_trade_scan,
    trade_payloads_from_message,
)


WALLET_A = "0x" + "a" * 40
WALLET_B = "0x" + "b" * 40


def _trade_message(coin="BTC", px="100", sz="2"):
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
                    "time": 1_700_000_000_000,
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


def test_public_trades_scan_discovers_wallets_without_info_api():
    result = ingest_public_trade_messages([_trade_message(), _trade_message(coin="ETH", px="200", sz="1")])

    assert result.trades_seen == 2
    assert len(result.wallet_stats) == 2
    assert result.wallet_stats[WALLET_A.lower()].observed_notional_usdc == 400
    assert result.wallet_stats[WALLET_A.lower()].coins == {"BTC", "ETH"}


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
