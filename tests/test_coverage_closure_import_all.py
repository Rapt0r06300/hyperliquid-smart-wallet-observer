from __future__ import annotations

import importlib
import pkgutil
import socket

import hl_observer


def test_all_hl_observer_modules_are_import_safe_offline(monkeypatch) -> None:
    """Every package module must import without network or execution side effects."""

    for key, value in {
        "HL_ENABLE_MAINNET_EXECUTION": "0",
        "HL_ENABLE_TESTNET_EXECUTION": "0",
        "REAL_MAINNET_TRADING": "false",
        "HYPERSMART_ENABLE_REAL_ORDERS": "0",
        "ENABLE_REAL_ORDERS": "0",
    }.items():
        monkeypatch.setenv(key, value)

    def blocked_connect(*args, **kwargs):
        raise AssertionError("network access during module import is forbidden")

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)

    modules = sorted(
        info.name
        for info in pkgutil.walk_packages(hl_observer.__path__, prefix="hl_observer.")
    )
    assert modules

    failures: dict[str, str] = {}
    for module_name in modules:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # diagnostic contract: report every unsafe import together
            failures[module_name] = f"{type(exc).__name__}: {exc}"
            continue
        assert module.__name__ == module_name

    assert not failures, "unsafe/import-broken modules: " + repr(failures)
