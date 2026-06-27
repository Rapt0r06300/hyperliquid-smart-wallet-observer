from hl_observer.config.loader import load_settings
from hl_observer.config.settings import ExecutionEnvironment


def test_private_key_not_required_for_read_only(monkeypatch):
    monkeypatch.setenv("HL_ENV", "read_only")
    monkeypatch.delenv("HL_TESTNET_PRIVATE_KEY", raising=False)

    settings = load_settings()

    assert settings.environment == ExecutionEnvironment.READ_ONLY
    assert settings.read_only_or_paper


def test_private_key_not_required_for_paper(monkeypatch):
    monkeypatch.setenv("HL_ENV", "paper")
    monkeypatch.delenv("HL_TESTNET_PRIVATE_KEY", raising=False)

    settings = load_settings()

    assert settings.environment == ExecutionEnvironment.PAPER
    assert settings.read_only_or_paper
    assert not settings.execution.enable_testnet_execution
