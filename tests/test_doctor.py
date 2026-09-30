from typer.testing import CliRunner

from hl_observer.cli import app


def test_doctor_command_passes_baseline(monkeypatch):
    monkeypatch.setenv("HL_ENV", "paper")
    monkeypatch.setenv("HL_ENABLE_MAINNET_EXECUTION", "false")
    runner = CliRunner()

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "mainnet_execution_disabled: ok" in result.output
