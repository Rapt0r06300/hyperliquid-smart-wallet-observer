from __future__ import annotations

import importlib
import inspect
import os
import pkgutil
from builtins import BaseExceptionGroup
from collections import deque
from pathlib import Path

import hl_observer

from hl_observer.config import Settings
from tests import coverage_contract_harness as harness
from tests import test_coverage_closure_branch_fuzzer_v2 as v2
from tests.test_coverage_closure_dynamic_edges import _install_offline_guards, _method_function

MAX_DISCOVERED_PER_MODULE = 320
MAX_PRIORITY_CASES = 96
MAX_NORMAL_CASES = 36


def _production_modules() -> tuple[str, ...]:
    return tuple(
        sorted(
            info.name
            for info in pkgutil.walk_packages(hl_observer.__path__, prefix="hl_observer.")
        )
    )


def _targets_for_shard() -> tuple[str, ...]:
    modules = _production_modules()
    raw = os.getenv("HYPERSMART_COVERAGE_CONTRACT_SHARD")
    if raw is None:
        return modules
    shard = int(raw)
    total = int(os.getenv("COVERAGE_SHARDS", "32"))
    assert 0 <= shard < total
    return modules[shard::total]


def _functions_in_value(value: object, module_name: str, depth: int = 0):
    if depth > 2:
        return
    if inspect.isfunction(value) and getattr(value, "__module__", None) == module_name:
        yield value
        return
    if isinstance(value, dict):
        for item in list(value.values())[:80]:
            yield from _functions_in_value(item, module_name, depth + 1)
        return
    if isinstance(value, (list, tuple, set)):
        for item in list(value)[:80]:
            yield from _functions_in_value(item, module_name, depth + 1)


def _closure_functions(function, module_name: str):
    closure = getattr(function, "__closure__", None) or ()
    for cell in closure:
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        yield from _functions_in_value(value, module_name)
    try:
        variables = inspect.getclosurevars(function)
    except (TypeError, ValueError):
        return
    for value in variables.nonlocals.values():
        yield from _functions_in_value(value, module_name)


def _materialized_functions(function, module_name: str, tmp_path: Path, settings: Settings):
    if not v2._safe_any(function, module_name, getattr(function, "__name__", "")):
        return
    if inspect.iscoroutinefunction(function) or inspect.isasyncgenfunction(function):
        return
    try:
        positional, keyword = v2._build_arguments(
            function,
            mode=1,
            tmp_path=tmp_path,
            settings=settings,
        )
        result = function(*positional, **keyword)
    except BaseExceptionGroup as error:
        if not harness._controlled_group(error):
            raise
        return
    except (Exception, SystemExit):
        return

    yield from _functions_in_value(result, module_name)
    routes = getattr(result, "routes", None)
    if isinstance(routes, list):
        for route in list(routes):
            endpoint = getattr(route, "endpoint", None)
            if inspect.isfunction(endpoint) and getattr(endpoint, "__module__", None) == module_name:
                yield endpoint


def test_sharded_closure_fuzzer_executes_nested_real_helpers(tmp_path, monkeypatch) -> None:
    _install_offline_guards(monkeypatch)
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)
    for name, value in {
        "HL_ENABLE_MAINNET_EXECUTION": "0",
        "HL_ENABLE_TESTNET_EXECUTION": "0",
        "REAL_MAINNET_TRADING": "false",
        "TESTNET_EXECUTION_ENABLED": "false",
        "HYPERSMART_ENABLE_REAL_ORDERS": "0",
        "ENABLE_REAL_ORDERS": "0",
    }.items():
        monkeypatch.setenv(name, value)

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'closure-fuzzer.sqlite3'}",
        logs_dir=str(tmp_path / "closure-fuzzer-logs"),
    )
    imported = 0
    attempts = 0

    for module_name in _targets_for_shard():
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        imported += 1
        max_cases = (
            MAX_PRIORITY_CASES if module_name in v2.PRIORITY_MODULES else MAX_NORMAL_CASES
        )
        queue = deque()
        seen: set[int] = set()

        for value in list(vars(module).values()):
            if inspect.isfunction(value) and getattr(value, "__module__", None) == module_name:
                queue.append(value)
            elif inspect.isclass(value) and getattr(value, "__module__", None) == module_name:
                for descriptor in list(vars(value).values()):
                    function = _method_function(descriptor)
                    if function is not None and getattr(function, "__module__", None) == module_name:
                        queue.append(function)

        while queue and len(seen) < MAX_DISCOVERED_PER_MODULE:
            function = queue.popleft()
            marker = id(function)
            if marker in seen:
                continue
            seen.add(marker)
            name = getattr(function, "__name__", type(function).__name__)
            attempts += v2._exercise_callable(
                function,
                module_name,
                name,
                tmp_path,
                settings,
                max_cases=max_cases,
            )
            for nested in _closure_functions(function, module_name):
                if id(nested) not in seen:
                    queue.append(nested)
            for nested in _materialized_functions(function, module_name, tmp_path, settings):
                if id(nested) not in seen:
                    queue.append(nested)

    assert imported >= 1
    assert attempts >= 1
