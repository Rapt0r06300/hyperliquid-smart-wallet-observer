"""Cover pure endpoint selection without importing the full runtime configuration stack."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _load_endpoints(monkeypatch):
    testnet = object()

    class ExecutionEnvironment:
        TESTNET = testnet

    class Settings:
        pass

    root = types.ModuleType("hl_observer")
    config = types.ModuleType("hl_observer.config")
    settings_module = types.ModuleType("hl_observer.config.settings")
    settings_module.ExecutionEnvironment = ExecutionEnvironment
    settings_module.Settings = Settings
    monkeypatch.setitem(sys.modules, "hl_observer", root)
    monkeypatch.setitem(sys.modules, "hl_observer.config", config)
    monkeypatch.setitem(sys.modules, "hl_observer.config.settings", settings_module)

    source = Path(__file__).resolve().parents[1] / "src" / "hl_observer" / "hyperliquid" / "endpoints.py"
    spec = importlib.util.spec_from_file_location("_endpoints_gap_target", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, testnet


def test_mainnet_and_testnet_read_endpoints_are_selected(monkeypatch) -> None:
    endpoints, testnet = _load_endpoints(monkeypatch)
    hyperliquid = SimpleNamespace(
        info_base_url="https://mainnet.example/info",
        testnet_info_base_url="https://testnet.example/info",
        ws_base_url="wss://mainnet.example/ws",
        testnet_ws_base_url="wss://testnet.example/ws",
    )

    mainnet_settings = SimpleNamespace(environment=object(), hyperliquid=hyperliquid)
    testnet_settings = SimpleNamespace(environment=testnet, hyperliquid=hyperliquid)

    assert endpoints.info_url_for_settings(mainnet_settings) == "https://mainnet.example/info"
    assert endpoints.ws_url_for_settings(mainnet_settings) == "wss://mainnet.example/ws"
    assert endpoints.info_url_for_settings(testnet_settings) == "https://testnet.example/info"
    assert endpoints.ws_url_for_settings(testnet_settings) == "wss://testnet.example/ws"
