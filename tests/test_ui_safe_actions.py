from __future__ import annotations

import asyncio
import inspect

from hl_observer.config.loader import load_settings
from hl_observer.ui import safe_actions
from hl_observer.ui.safe_actions import run_safe_action
from hl_observer.ui.state import UiState


def test_ui_safe_action_doctor_allowed(monkeypatch):
    monkeypatch.setenv("HL_ENABLE_MAINNET_EXECUTION", "false")
    settings = load_settings()
    state = UiState()

    result = asyncio.run(run_safe_action("doctor", settings, state))

    assert result.allowed
    assert result.success


def test_ui_safe_action_unknown_rejected():
    settings = load_settings()
    state = UiState()

    result = asyncio.run(run_safe_action("run_any_shell", settings, state))

    assert not result.allowed
    assert not result.success
    assert result.level == "SECURITY"


def test_ui_safe_action_never_calls_shell_arbitrary():
    source = inspect.getsource(safe_actions)

    assert "subprocess" not in source
    assert "os.system" not in source
    assert "shell=True" not in source


def test_ui_safe_action_mainnet_rejected(monkeypatch):
    monkeypatch.setenv("HL_ENABLE_MAINNET_EXECUTION", "true")
    settings = load_settings()
    state = UiState()

    result = asyncio.run(run_safe_action("doctor", settings, state))

    assert not result.allowed
    assert result.level == "SECURITY"


def test_ui_kill_switch_blocks_sensitive_actions():
    settings = load_settings()
    state = UiState(kill_switch_active=True)

    result = asyncio.run(run_safe_action("paper_run", settings, state))

    assert not result.allowed
    assert not result.success
    assert result.level == "RISK"
