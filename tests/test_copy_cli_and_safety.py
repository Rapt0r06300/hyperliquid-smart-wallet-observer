from pathlib import Path

from typer.testing import CliRunner

from hl_observer.cli import _resolve_public_trade_scan_coins, _selected_top_wallet_rows, _unique_top_wallet_rows, app
from hl_observer.config.loader import load_settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import MarketUniverseModel, TopWallet
from hl_observer.utils.time import now_ms


def test_copy_run_command_exists_and_defaults_to_dry_run():
    result = CliRunner().invoke(app, ["copy-run", "--help"])

    assert result.exit_code == 0
    help_text = result.output.lower()
    assert "copy-run" in help_text
    assert "dry-run" in help_text
    assert "polling interval" in help_text
    assert "consensus" in help_text


def test_copy_report_command_exists():
    result = CliRunner().invoke(app, ["copy-report", "--help"])

    assert result.exit_code == 0
    assert "--period" in result.output


def test_consensus_leader_report_command_exists():
    result = CliRunner().invoke(app, ["consensus-leader-report", "--help"])

    assert result.exit_code == 0
    assert "consensus" in result.output.lower()
    assert "same-coin" in result.output.lower()


def test_copy_preflight_command_exists():
    result = CliRunner().invoke(app, ["copy-preflight", "--help"])

    assert result.exit_code == 0
    assert "--network-read" in result.output
    assert "--copy-max-leaders" in result.output


def test_throughput_plan_cli_refuses_bypass_and_keeps_safe_rotation():
    runner = CliRunner()
    override = runner.invoke(app, ["throughput-plan", "--network-read", "--bypass-requested"])
    rotated = runner.invoke(
        app,
        [
            "throughput-plan",
            "--network-read",
            "--ws",
            "--requested-wallets",
            "50",
            "--rest-weight-remaining",
            "100",
            "--max-leaders-per-run",
            "50",
        ],
    )

    assert override.exit_code == 2
    assert "scanner_starts=no" in override.output
    assert "RATE_LIMIT_BYPASS_REFUSED" in override.output
    assert "BYPASS_OVERRIDE_ACTIVE" not in override.output
    assert "execution=forbidden" in override.output
    assert rotated.exit_code == 0
    assert "scanner_starts=yes" in rotated.output
    assert "SAFE_ROTATION_ACTIVE" in rotated.output
    assert "execution=forbidden" in rotated.output


def test_fresh_scan_plan_cli_maximizes_fresh_coverage_without_bypass(tmp_path, monkeypatch):
    db_path = tmp_path / "fresh_scan.sqlite3"
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))
    init_db(f"sqlite:///{db_path}")
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "fresh-scan-plan",
            "--network-read",
            "--requested-wallets",
            "50000",
            "--cycle-seconds",
            "15",
            "--public-trade-wallets",
            "10000",
            "--leaders-per-stream",
            "50",
        ],
    )
    override = runner.invoke(app, ["fresh-scan-plan", "--network-read", "--bypass-requested"])

    assert result.exit_code == 0
    assert "fresh_scan_plan=read_only_safe" in result.output
    assert "public_trade_scan_every_polls=1" in result.output
    assert "public_trade_wallet_cap=10000" in result.output
    assert "user_fills_ws_users=10/10" in result.output
    assert "execution=forbidden" in result.output
    assert "real_orders_created=0" in result.output
    assert override.exit_code == 2
    assert "scanner_starts=no" in override.output
    assert "RATE_LIMIT_BYPASS_REFUSED" in override.output


def test_fresh_data_plan_cli_reports_max_fresh_collection_shape(tmp_path, monkeypatch):
    db_path = tmp_path / "fresh_data.sqlite3"
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))
    init_db(f"sqlite:///{db_path}")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "fresh-data-plan",
            "--network-read",
            "--requested-wallets",
            "50000",
            "--coins",
            "BTC,ETH,HYPE",
            "--max-hot-wallets",
            "50",
            "--gap-recovery",
        ],
    )

    assert result.exit_code == 0
    assert "fresh_data_plan=read_only_safe" in result.output
    assert "public_streams=3" in result.output
    assert "hot_user_streams=0/10" in result.output
    assert "execution=forbidden" in result.output
    assert "real_orders_created=0" in result.output


def test_dashboard_export_command_exists():
    result = CliRunner().invoke(app, ["dashboard-export", "--help"])

    assert result.exit_code == 0
    assert "read-only" in result.output.lower()


def test_live_user_fills_scan_command_exists_and_requires_network_read():
    runner = CliRunner()
    help_result = runner.invoke(app, ["live-user-fills-scan", "--help"])
    refused = runner.invoke(app, ["live-user-fills-scan", "--duration-seconds", "1", "--dry-run"])

    assert help_result.exit_code == 0
    assert "--max-users" in help_result.output
    assert "--leader-offset" in help_result.output
    assert "--max-live-fill-age-ms" in help_result.output
    assert refused.exit_code != 0
    assert "--network-read is required" in refused.output


def test_copy_run_dedupes_promoted_wallet_rows_before_scanning():
    rows = [
        TopWallet(wallet_address="0x" + "a" * 40, rank=1, source="public_trades_ws", score=100, selected_at_ms=1, status="selected"),
        TopWallet(wallet_address="0x" + "a" * 40, rank=2, source="public_trades_ws", score=99, selected_at_ms=2, status="selected"),
        TopWallet(wallet_address="0x" + "b" * 40, rank=3, source="public_trades_ws", score=98, selected_at_ms=3, status="selected"),
    ]

    unique = _unique_top_wallet_rows(rows, limit=2)

    assert [row.wallet_address for row in unique] == ["0x" + "a" * 40, "0x" + "b" * 40]


def test_top_wallet_dedupe_supports_rotation_offset():
    rows = [
        TopWallet(wallet_address="0x" + "a" * 40, rank=1, source="public_trades_ws", score=100, selected_at_ms=1, status="selected"),
        TopWallet(wallet_address="0x" + "a" * 40, rank=2, source="public_trades_ws", score=99, selected_at_ms=2, status="selected"),
        TopWallet(wallet_address="0x" + "b" * 40, rank=3, source="public_trades_ws", score=98, selected_at_ms=3, status="selected"),
        TopWallet(wallet_address="0x" + "c" * 40, rank=4, source="public_trades_ws", score=97, selected_at_ms=4, status="selected"),
    ]

    rotated = _unique_top_wallet_rows(rows, limit=2, offset=1)

    assert [row.wallet_address for row in rotated] == ["0x" + "b" * 40, "0x" + "c" * 40]


def test_top_wallet_dedupe_wraps_offset_when_unique_pool_is_smaller_than_configured_pool():
    rows = [
        TopWallet(wallet_address="0x" + "a" * 40, rank=1, source="public_trades_ws", score=100, selected_at_ms=1, status="selected"),
        TopWallet(wallet_address="0x" + "b" * 40, rank=2, source="public_trades_ws", score=99, selected_at_ms=2, status="selected"),
        TopWallet(wallet_address="0x" + "c" * 40, rank=3, source="public_trades_ws", score=98, selected_at_ms=3, status="selected"),
    ]

    wrapped = _unique_top_wallet_rows(rows, limit=2, offset=45)

    assert [row.wallet_address for row in wrapped] == ["0x" + "a" * 40, "0x" + "b" * 40]


def test_top_wallet_dedupe_wraps_and_fills_requested_batch_after_offset():
    rows = [
        TopWallet(wallet_address="0x" + "a" * 40, rank=1, source="public_trades_ws", score=100, selected_at_ms=1, status="selected"),
        TopWallet(wallet_address="0x" + "b" * 40, rank=2, source="public_trades_ws", score=99, selected_at_ms=2, status="selected"),
        TopWallet(wallet_address="0x" + "c" * 40, rank=3, source="public_trades_ws", score=98, selected_at_ms=3, status="selected"),
        TopWallet(wallet_address="0x" + "d" * 40, rank=4, source="public_trades_ws", score=97, selected_at_ms=4, status="selected"),
    ]

    wrapped = _unique_top_wallet_rows(rows, limit=3, offset=3)

    assert [row.wallet_address for row in wrapped] == [
        "0x" + "d" * 40,
        "0x" + "a" * 40,
        "0x" + "b" * 40,
    ]


def test_live_public_scan_auto_coins_uses_stored_market_universe(tmp_path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'coins.sqlite3'}"
    init_db(settings.database_url)
    session_factory = create_session_factory(create_sqlite_engine(settings.database_url))
    stamp = now_ms()
    with session_factory() as session:
        session.add_all(
            [
                MarketUniverseModel(coin="ZEC", source="meta", is_active=True, is_spot=False, first_seen_ms=stamp, last_seen_ms=stamp, mid_price=1.0, notes="test"),
                MarketUniverseModel(coin="ONDO", source="meta", is_active=True, is_spot=False, first_seen_ms=stamp, last_seen_ms=stamp, mid_price=1.0, notes="test"),
            ]
        )
        session.commit()

    coins = _resolve_public_trade_scan_coins(settings, "AUTO", max_coins=12)

    assert "BTC" in coins
    assert "ZEC" in coins
    assert "ONDO" in coins
    assert not any(coin.startswith(("@", "#")) for coin in coins)
    assert len(coins) <= 12


def test_live_leader_selection_prioritizes_recent_public_trade_wallets(tmp_path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'leaders.sqlite3'}"
    init_db(settings.database_url)
    session_factory = create_session_factory(create_sqlite_engine(settings.database_url))
    stamp = now_ms()
    old_wallet = "0x" + "a" * 40
    recent_wallet = "0x" + "b" * 40
    with session_factory() as session:
        session.add_all(
            [
                TopWallet(wallet_address=old_wallet, rank=1, source="public_trades_ws", score=1000, selected_at_ms=stamp - 900_000, status="selected"),
                TopWallet(wallet_address=recent_wallet, rank=2, source="public_trades_ws", score=80, selected_at_ms=stamp, status="selected"),
            ]
        )
        session.commit()

        selected = _selected_top_wallet_rows(session, limit=1, active_window_ms=300_000)

    assert [row.wallet_address for row in selected] == [recent_wallet]


def test_runtime_check_commands_exist():
    runner = CliRunner()

    assert runner.invoke(app, ["runtime-check", "--help"]).exit_code == 0
    assert runner.invoke(app, ["runtime-clean-report", "--help"]).exit_code == 0
    assert runner.invoke(app, ["audit-safety", "--help"]).exit_code == 0
    reset_help = runner.invoke(app, ["reset-simulation-state", "--help"])
    assert reset_help.exit_code == 0
    assert "--starting-equity" in reset_help.output


def test_copy_batch_keeps_testnet_and_mainnet_disabled_by_default():
    settings = load_settings()

    assert settings.execution.enable_mainnet_execution is False
    assert settings.execution.enable_testnet_execution is False
    assert settings.copy_trading.top_leaders == 50
    assert settings.copy_trading.dry_run_default is True
    assert settings.copy_trading.mode_default == "PAPER_MOCK_USDC"


def test_copy_batch_contains_no_exchange_or_private_key_hot_path():
    hot_paths = [
        Path("src/hl_observer/copying"),
        Path("src/hl_observer/runtime"),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for root in hot_paths for path in root.rglob("*.py"))

    assert "/exchange" not in text
    assert "private_key" not in text.lower()
    assert "place_order" not in text.lower()
