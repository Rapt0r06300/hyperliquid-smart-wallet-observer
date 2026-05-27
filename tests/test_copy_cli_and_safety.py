from pathlib import Path

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.config.loader import load_settings


def test_copy_run_command_exists_and_defaults_to_dry_run():
    result = CliRunner().invoke(app, ["copy-run", "--help"])

    assert result.exit_code == 0
    assert "--interval" in result.output
    assert "--dry-run" in result.output
    assert "--fresh-window-minutes" in result.output
    assert "--leader-offset" in result.output


def test_copy_report_command_exists():
    result = CliRunner().invoke(app, ["copy-report", "--help"])

    assert result.exit_code == 0
    assert "--period" in result.output


def test_runtime_check_commands_exist():
    runner = CliRunner()

    assert runner.invoke(app, ["runtime-check", "--help"]).exit_code == 0
    assert runner.invoke(app, ["runtime-clean-report", "--help"]).exit_code == 0


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
