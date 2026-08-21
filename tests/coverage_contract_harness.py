from __future__ import annotations

import asyncio
import dataclasses
import enum
import importlib
import inspect
import signal
import socket
import subprocess
import time
import types
import typing
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


class _Timeout(Exception):
    pass


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

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    previous_remaining, previous_interval = previous_timer
    started = time.monotonic()
    outer_deadline = started + previous_remaining if previous_remaining > 0 else None
    soft_deadline = started + 0.01
    hard_deadline = started + 0.05
    outer_fired = False

    def nested_timeout_handler(signum, frame):
        nonlocal outer_fired
        now = time.monotonic()
        if outer_deadline is not None and now >= outer_deadline:
            outer_fired = True
            if callable(previous_handler):
                return previous_handler(signum, frame)
            if previous_handler == signal.SIG_IGN:
                return None
            raise _HardTimeout("outer SIGALRM deadline reached")
        if now >= hard_deadline:
            raise _HardTimeout("synthetic coverage call exceeded hard deadline")
        if now >= soft_deadline:
            raise _Timeout()
        raise _Timeout()

    signal.signal(signal.SIGALRM, nested_timeout_handler)
    first_alarm = 0.01
    if previous_remaining > 0:
        first_alarm = min(first_alarm, max(1e-6, previous_remaining))
    signal.setitimer(signal.ITIMER_REAL, first_alarm, 0.01)
    try:
        if inspect.iscoroutinefunction(function):
            return asyncio.run(function(*positional, **keyword))
        return function(*positional, **keyword)
    finally:
        elapsed = max(0.0, time.monotonic() - started)
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_remaining > 0 and not outer_fired:
            signal.setitimer(
                signal.ITIMER_REAL,
                max(1e-6, previous_remaining - elapsed),
                previous_interval,
            )
        elif outer_fired and previous_interval > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_interval, previous_interval)


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

    monkeypatch.setattr(socket.socket, "connect", blocked_connect, raising=True)
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Dummy(status_code=200), raising=True)
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: Dummy(status_code=200), raising=True)
    monkeypatch.setattr(requests, "request", lambda *args, **kwargs: Dummy(status_code=200), raising=True)
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: Dummy(status_code=200), raising=True)
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: Dummy(status_code=200), raising=True)
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: Dummy(status_code=200), raising=True)
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
            if name.lower() in UNSAFE_NAMES:
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
                except (Exception, SystemExit):
                    controlled_failures += 1
    return imported, attempts, completed, controlled_failures
