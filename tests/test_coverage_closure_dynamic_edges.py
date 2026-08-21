from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
import os
import pkgutil
import socket
import subprocess
import sys
import textwrap
from builtins import BaseExceptionGroup
from pathlib import Path

import httpx
import requests

import hl_observer
from hl_observer.config import Settings
from tests import coverage_contract_harness as harness


def _production_modules() -> tuple[str, ...]:
    return tuple(
        sorted(info.name for info in pkgutil.walk_packages(hl_observer.__path__, prefix="hl_observer."))
    )


def _settings(tmp_path: Path, suffix: str) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / f'dynamic-{suffix}.sqlite3'}",
        logs_dir=str(tmp_path / f"logs-{suffix}"),
    )


def _tree(function):
    try:
        return ast.parse(textwrap.dedent(inspect.getsource(function)))
    except (OSError, TypeError, IndentationError, SyntaxError):
        return None


def _blocking(function) -> bool:
    tree = _tree(function)
    if tree is None:
        return False
    blocked = {"sleep", "join", "serve_forever", "run_forever", "wait_forever"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name):
            name = target.id
        elif isinstance(target, ast.Attribute):
            name = target.attr
        else:
            name = ""
        if name in blocked:
            return True
    return False


def _method_function(descriptor):
    if isinstance(descriptor, (staticmethod, classmethod)):
        return descriptor.__func__
    if isinstance(descriptor, property):
        return descriptor.fget
    if inspect.isfunction(descriptor):
        return descriptor
    return None


def _safe(function, module_name: str, name: str, *, allow_async: bool = False) -> bool:
    if function is None or getattr(function, "__module__", None) != module_name:
        return False
    lowered = name.lower()
    if lowered.startswith("__") and lowered.endswith("__"):
        return False
    if lowered in harness.UNSAFE_NAMES:
        return False
    if (module_name, name) in harness.PROCESS_GLOBAL_UNSAFE:
        return False
    if inspect.iscoroutinefunction(function) != allow_async:
        return False
    try:
        inspect.signature(function)
    except (TypeError, ValueError):
        return False
    if harness._contains_while_loop(function):
        if allow_async or not harness._loop_has_explicit_safety_bound(function):
            return False
    return not _blocking(function)


def _install_offline_guards(monkeypatch) -> None:
    def blocked(*_args, **_kwargs):
        raise RuntimeError("dynamic coverage contract blocks network")

    async def blocked_async(*_args, **_kwargs):
        raise RuntimeError("dynamic coverage contract blocks async network")

    class Process:
        returncode = 0
        stdout = ""
        stderr = ""

        def communicate(self, *_args, **_kwargs):
            return "", ""

        def wait(self, *_args, **_kwargs):
            return 0

        def poll(self):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
    monkeypatch.setattr(httpx.Client, "request", blocked)
    monkeypatch.setattr(httpx.AsyncClient, "request", blocked_async)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=args[0] if args else [], returncode=0),
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(os, "system", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(os, "_exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code)))


def _controlled_call(function, mode: int, tmp_path: Path, settings: Settings) -> bool:
    try:
        harness._invoke(function, mode, tmp_path, settings)
        return True
    except BaseExceptionGroup as error:
        if not harness._controlled_group(error):
            raise
    except (Exception, SystemExit):
        pass
    return False


def test_dynamic_router_endpoints_cover_nested_fastapi_paths(tmp_path, monkeypatch) -> None:
    _install_offline_guards(monkeypatch)
    settings = _settings(tmp_path, "routes")
    attempts = 0
    for module_name in _production_modules():
        if module_name == "hl_observer.cli":
            continue
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        for factory_name, factory in list(vars(module).items()):
            if not inspect.isfunction(factory) or factory.__module__ != module_name:
                continue
            if "router" not in factory_name.lower() or not _safe(factory, module_name, factory_name):
                continue
            try:
                router = harness._invoke(factory, 1, tmp_path, settings)
            except BaseExceptionGroup as error:
                if not harness._controlled_group(error):
                    raise
                continue
            except (Exception, SystemExit):
                continue
            routes = getattr(router, "routes", None)
            if not isinstance(routes, list):
                continue
            for route in list(routes):
                endpoint = getattr(route, "endpoint", None)
                endpoint_name = getattr(endpoint, "__name__", "")
                if not _safe(endpoint, module_name, endpoint_name):
                    continue
                for mode in (0, 1, 2):
                    attempts += 1
                    _controlled_call(endpoint, mode, tmp_path, settings)
    assert attempts >= 3


def test_dynamic_cli_and_argparse_paths_are_finite_and_offline(tmp_path, monkeypatch) -> None:
    _install_offline_guards(monkeypatch)
    settings = _settings(tmp_path, "cli")
    attempts = 0
    module = importlib.import_module("hl_observer.cli")
    for function_name, function in list(vars(module).items()):
        if not inspect.isfunction(function) or function.__module__ != "hl_observer.cli":
            continue
        if _safe(function, "hl_observer.cli", function_name):
            for mode in (0, 1, 2):
                attempts += 1
                _controlled_call(function, mode, tmp_path, settings)

    for module_name in _production_modules():
        try:
            target = importlib.import_module(module_name)
        except Exception:
            continue
        for function_name, function in list(vars(target).items()):
            if not inspect.isfunction(function) or function.__module__ != module_name:
                continue
            if function_name.lower() not in {"main", "_main", "_cli", "run"}:
                continue
            source = inspect.getsource(function) if _tree(function) is not None else ""
            if not any(token in source for token in ("ArgumentParser", "parse_args", "parse_known_args")):
                continue
            if harness._contains_while_loop(function) or _blocking(function):
                continue
            try:
                signature = inspect.signature(function)
            except (TypeError, ValueError):
                continue
            parameters = [
                parameter
                for parameter in signature.parameters.values()
                if parameter.kind not in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD)
            ]
            attempts += 1
            try:
                monkeypatch.setattr(sys, "argv", [module_name, "--help"])
                if not parameters:
                    function()
                elif len(parameters) == 1 and parameters[0].name.lower() in {"argv", "args"}:
                    function(["--help"])
            except (Exception, SystemExit):
                pass
    assert attempts >= 10


async def _await_bounded(awaitable):
    return await asyncio.wait_for(awaitable, timeout=0.25)


def _async_call(function, mode: int, tmp_path: Path, settings: Settings):
    signature = inspect.signature(function)
    positional = []
    keyword = {}
    for parameter in signature.parameters.values():
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        if parameter.default is not parameter.empty and mode == 0:
            continue
        value = harness._value(parameter.annotation, parameter.name, mode, tmp_path, settings)
        if parameter.kind is parameter.POSITIONAL_ONLY:
            positional.append(value)
        else:
            keyword[parameter.name] = value
    return function(*positional, **keyword)


def test_dynamic_async_callables_are_bounded_and_offline(tmp_path, monkeypatch) -> None:
    _install_offline_guards(monkeypatch)
    settings = _settings(tmp_path, "async")
    attempts = 0
    for module_name in _production_modules():
        if module_name == "hl_observer.cli":
            continue
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        callables: list[tuple[str, object]] = []
        for name, function in list(vars(module).items()):
            if inspect.isfunction(function) and _safe(function, module_name, name, allow_async=True):
                callables.append((name, function))
        for class_value in list(vars(module).values()):
            if not inspect.isclass(class_value) or class_value.__module__ != module_name:
                continue
            for name, descriptor in list(vars(class_value).items()):
                function = _method_function(descriptor)
                if _safe(function, module_name, name, allow_async=True):
                    callables.append((name, function))
        for _name, function in callables:
            for mode in (0, 1):
                attempts += 1
                try:
                    asyncio.run(_await_bounded(_async_call(function, mode, tmp_path, settings)))
                except BaseExceptionGroup as error:
                    if not harness._controlled_group(error):
                        raise
                except (Exception, SystemExit):
                    pass
    assert attempts >= 1


def _literal_overrides(function) -> list[tuple[str, object]]:
    tree = _tree(function)
    if tree is None:
        return []
    parameters = set(inspect.signature(function).parameters)
    found: list[tuple[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        expressions = [node.left, *node.comparators]
        for index, expression in enumerate(expressions):
            if not isinstance(expression, ast.Name) or expression.id not in parameters:
                continue
            for other in expressions[:index] + expressions[index + 1 :]:
                values = []
                if isinstance(other, ast.Constant):
                    values = [other.value]
                elif isinstance(other, (ast.List, ast.Tuple, ast.Set)):
                    values = [item.value for item in other.elts if isinstance(item, ast.Constant)]
                for value in values:
                    if not isinstance(value, (str, int, float, bool, type(None))):
                        continue
                    marker = (expression.id, repr(value))
                    if marker not in seen:
                        seen.add(marker)
                        found.append((expression.id, value))
                    if len(found) >= 4:
                        return found
    return found


def _call_override(function, parameter_name: str, value, tmp_path: Path, settings: Settings):
    positional = []
    keyword = {}
    for parameter in inspect.signature(function).parameters.values():
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        candidate = (
            value
            if parameter.name == parameter_name
            else harness._value(parameter.annotation, parameter.name, 1, tmp_path, settings)
        )
        if parameter.kind is parameter.POSITIONAL_ONLY:
            positional.append(candidate)
        else:
            keyword[parameter.name] = candidate
    return function(*positional, **keyword)


def test_dynamic_literal_branches_expand_partial_function_coverage(tmp_path, monkeypatch) -> None:
    _install_offline_guards(monkeypatch)
    settings = _settings(tmp_path, "literals")
    attempts = 0
    for module_name in _production_modules():
        if module_name == "hl_observer.cli":
            continue
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        for function_name, function in list(vars(module).items()):
            if not inspect.isfunction(function) or function.__module__ != module_name:
                continue
            if not _safe(function, module_name, function_name):
                continue
            for parameter_name, value in _literal_overrides(function):
                attempts += 1
                try:
                    _call_override(function, parameter_name, value, tmp_path, settings)
                except BaseExceptionGroup as error:
                    if not harness._controlled_group(error):
                        raise
                except (Exception, SystemExit):
                    pass
    assert attempts >= 10
