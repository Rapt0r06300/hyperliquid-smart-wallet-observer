from __future__ import annotations

import asyncio
import dataclasses
import enum
import importlib
import inspect
import socket
import subprocess
import sys
import time
import types
import typing
from builtins import BaseExceptionGroup
from pathlib import Path

import httpx
import requests

from hl_observer.config import Settings
from hl_observer.ui.state import UiState

WALLET = "0x" + "1" * 40
UNSAFE_NAMES = {
    "main",
    "_main",
    "_cli",
    "_run_cli",
    "run",
    "serve",
    "listen",
    "connect",
    "download",
    "upload",
    "spawn",
    "launch",
    "start_server",
    "run_forever",
}
PROCESS_GLOBAL_UNSAFE = {
    ("hl_observer.ops.portable_audit_guard", "install"),
    ("hl_observer.ops.portable_audit_guard", "install_from_environment"),
}
_INTERNAL_TIMEOUT_SECONDS = 0.05


class _HardTimeout(SystemExit):
    """Borne dure qui traverse les `except Exception` du code exercé."""


class Dummy:
    def __init__(self, **values):
        self.__dict__.update(values)

    def __getattr__(self, name):
        if name == "json":
            return lambda: {}
        if name in {"status_code", "returncode"}:
            return 200 if name == "status_code" else 0
        if name in {"text", "content", "stdout", "stderr"}:
            return ""
        if name.startswith("is_") or name.startswith("has_"):
            return False
        return Dummy()

    def __call__(self, *args, **kwargs):
        del args, kwargs
        return Dummy()

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __bool__(self):
        return False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        del args
        return False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        del args
        return False


def _value(annotation, name: str, mode: int, root: Path, settings: Settings, depth: int = 0):
    lower = name.lower()
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if "setting" in lower:
        return settings
    if lower in {"state", "ui_state"}:
        return UiState()
    if "wallet" in lower or lower == "address":
        return WALLET
    if lower in {"coin", "symbol", "asset", "base", "quote"}:
        return "BTC"
    if lower == "venue":
        return "hyperliquid"
    if any(token in lower for token in ("path", "file", "root", "dir", "output")):
        return root if "root" in lower or "dir" in lower else root / "sample.json"
    if "timestamp" in lower or lower.endswith("_ms") or lower in {"now", "now_ms", "ts"}:
        return (0, 1, 1000)[mode % 3]
    if any(
        token in lower
        for token in (
            "price",
            "mid",
            "size",
            "pnl",
            "fee",
            "bps",
            "score",
            "rate",
            "ratio",
            "threshold",
            "notional",
            "equity",
            "latency",
        )
    ):
        return (0.0, 1.0, 100.0)[mode % 3]
    if lower.startswith(("is_", "has_", "allow", "enable")):
        return bool(mode % 2)
    if origin in (typing.Union, types.UnionType):
        non_none = [item for item in args if item is not type(None)]
        if mode == 0 and type(None) in args:
            return None
        return _value(non_none[0] if non_none else typing.Any, name, mode, root, settings, depth + 1)
    if origin in (list, typing.List, typing.Sequence, typing.Iterable):
        return [] if mode == 0 else [1]
    if origin in (dict, typing.Dict, typing.Mapping):
        return {} if mode == 0 else {"BTC": 100.0}
    if origin in (set, typing.Set):
        return set() if mode == 0 else {"BTC"}
    if origin in (tuple, typing.Tuple):
        return ()
    if annotation is str:
        return "" if mode == 0 else "unit"
    if annotation is int:
        return (0, 1, -1)[mode % 3]
    if annotation is float:
        return (0.0, 1.0, -1.0)[mode % 3]
    if annotation is bool:
        return bool(mode % 2)
    if annotation is Path:
        return root / "sample.json"
    if inspect.isclass(annotation):
        try:
            if issubclass(annotation, enum.Enum):
                return list(annotation)[0]
        except (TypeError, ValueError):
            pass
        if dataclasses.is_dataclass(annotation) and depth < 2:
            values = {}
            for field in dataclasses.fields(annotation):
                if field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING:
                    continue
                values[field.name] = _value(field.type, field.name, mode, root, settings, depth + 1)
            try:
                return annotation(**values)
            except Exception:
                return Dummy()
        try:
            return annotation()
        except Exception:
            return Dummy()
    if lower in {
        "rows",
        "events",
        "fills",
        "positions",
        "deltas",
        "snapshots",
        "signals",
        "values",
        "items",
        "records",
        "wallets",
        "coins",
    }:
        return []
    if lower in {"payload", "data", "raw", "raw_json", "context", "metadata", "config", "mapping"}:
        return {}
    if lower in {"limit", "count", "index", "window", "seed"}:
        return (0, 1, 10)[mode % 3]
    return Dummy()


def _invoke(function, mode: int, root: Path, settings: Settings):
    signature = inspect.signature(function)
    positional = []
    keyword = {}
    for parameter in signature.parameters.values():
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        if parameter.default is not parameter.empty and mode == 0:
            continue
        value = _value(parameter.annotation, parameter.name, mode, root, settings)
        if parameter.kind is parameter.POSITIONAL_ONLY:
            positional.append(value)
        else:
            keyword[parameter.name] = value

    # Ne jamais utiliser SIGALRM ici: coverage.py tient des verrous internes pendant son
    # traçage et un signal asynchrone peut interrompre précisément une section critique,
    # provoquant un auto-deadlock. Un profile hook est synchrone avec l'interpréteur,
    # cohabite avec le traceur coverage et permet de borner les appels synthétiques sans
    # toucher au gestionnaire de signaux global du processus pytest.
    previous_profile = sys.getprofile()
    deadline = time.monotonic() + _INTERNAL_TIMEOUT_SECONDS

    def watchdog(frame, event, arg):
        if time.monotonic() >= deadline:
            raise _HardTimeout("synthetic coverage call exceeded hard deadline")
        if previous_profile is not None:
            previous_profile(frame, event, arg)

    sys.setprofile(watchdog)
    try:
        if inspect.iscoroutinefunction(function):
            return asyncio.run(function(*positional, **keyword))
        return function(*positional, **keyword)
    finally:
        sys.setprofile(previous_profile)


def _controlled_group(error: BaseExceptionGroup) -> bool:
    """N'avale que les sorties prévues du harnais, jamais KeyboardInterrupt."""
    for item in error.exceptions:
        if isinstance(item, BaseExceptionGroup):
            if not _controlled_group(item):
                return False
        elif not isinstance(item, (Exception, SystemExit)):
            return False
    return True


def run_typed_contracts(target_modules: tuple[str, ...], tmp_path: Path, monkeypatch) -> tuple[int, int, int, int]:
    for name, value in {
        "HL_ENABLE_MAINNET_EXECUTION": "0",
        "HL_ENABLE_TESTNET_EXECUTION": "0",
        "REAL_MAINNET_TRADING": "false",
        "TESTNET_EXECUTION_ENABLED": "false",
        "HYPERSMART_ENABLE_REAL_ORDERS": "0",
        "ENABLE_REAL_ORDERS": "0",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(tmp_path)

    def blocked_connect(*args, **kwargs):
        del args, kwargs
        raise AssertionError("network access is forbidden in coverage contracts")

    async def blocked_async_http(*args, **kwargs):
        del args, kwargs
        raise AssertionError("network access is forbidden in coverage contracts")

    monkeypatch.setattr(socket.socket, "connect", blocked_connect, raising=True)
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Dummy(status_code=200), raising=True)
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: Dummy(status_code=200), raising=True)
    monkeypatch.setattr(requests, "request", lambda *args, **kwargs: Dummy(status_code=200), raising=True)
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: Dummy(status_code=200), raising=True)
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: Dummy(status_code=200), raising=True)
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: Dummy(status_code=200), raising=True)
    monkeypatch.setattr(httpx.AsyncClient, "get", blocked_async_http, raising=True)
    monkeypatch.setattr(httpx.AsyncClient, "post", blocked_async_http, raising=True)
    monkeypatch.setattr(httpx.AsyncClient, "request", blocked_async_http, raising=True)
    monkeypatch.setattr(httpx.AsyncClient, "send", blocked_async_http, raising=True)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""),
        raising=True,
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: Dummy(), raising=True)
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'long-tail.sqlite3'}", logs_dir=str(tmp_path / "logs"))

    attempts = 0
    completed = 0
    controlled_failures = 0
    imported = 0
    for module_name in target_modules:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        imported += 1
        for name, function in list(vars(module).items()):
            if not inspect.isfunction(function) or function.__module__ != module_name:
                continue
            if name.lower() in UNSAFE_NAMES or (module_name, name) in PROCESS_GLOBAL_UNSAFE:
                continue
            try:
                inspect.signature(function)
            except (TypeError, ValueError):
                continue
            for mode in (0, 1, 2):
                attempts += 1
                try:
                    _invoke(function, mode, tmp_path, settings)
                    completed += 1
                except BaseExceptionGroup as error:
                    if not _controlled_group(error):
                        raise
                    controlled_failures += 1
                except (Exception, SystemExit):
                    controlled_failures += 1
    return imported, attempts, completed, controlled_failures
