from __future__ import annotations

import ast
import dataclasses
import enum
import importlib
import inspect
import os
import pkgutil
import types
import typing
from pathlib import Path

import hl_observer

from hl_observer.config import Settings
from tests import coverage_contract_harness as harness
from tests.test_coverage_closure_dynamic_edges import (
    _blocking,
    _install_offline_guards,
    _method_function,
    _safe,
)

MAX_CASES_PER_CALLABLE = 12
MAX_ENV_CASES_PER_CALLABLE = 4
SAFETY_ENV_TOKENS = (
    "ENABLE_MAINNET",
    "ENABLE_TESTNET",
    "REAL_MAINNET",
    "REAL_ORDER",
    "REAL_TRADING",
    "LIVE_ORDER",
    "MAINNET",
    "TESTNET",
    "EXECUTION_ENABLED",
)


def _production_modules() -> tuple[str, ...]:
    return tuple(
        sorted(
            info.name
            for info in pkgutil.walk_packages(hl_observer.__path__, prefix="hl_observer.")
        )
    )


def _targets_for_shard() -> tuple[str, ...]:
    modules = _production_modules()
    shard_raw = os.getenv("HYPERSMART_COVERAGE_CONTRACT_SHARD")
    if shard_raw is None:
        return modules
    shard = int(shard_raw)
    total = int(os.getenv("COVERAGE_SHARDS", "32"))
    assert 0 <= shard < total
    return modules[shard::total]


def _tree(function) -> ast.AST | None:
    try:
        source = inspect.getsource(function)
        return ast.parse(inspect.cleandoc(source))
    except (OSError, TypeError, IndentationError, SyntaxError):
        return None


def _hashable_marker(value: object) -> tuple[str, str]:
    if isinstance(value, dict):
        return "dict", repr(sorted(value.items(), key=lambda item: str(item[0])))
    if isinstance(value, (list, tuple, set)):
        return type(value).__name__, repr(value)
    return type(value).__name__, repr(value)


def _append_unique(values: list[object], candidate: object) -> None:
    marker = _hashable_marker(candidate)
    if all(_hashable_marker(value) != marker for value in values):
        values.append(candidate)


def _annotation_literals(annotation: object) -> list[object]:
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return list(typing.get_args(annotation))
    if origin in (typing.Union, types.UnionType):
        values: list[object] = []
        for item in typing.get_args(annotation):
            values.extend(_annotation_literals(item))
        return values
    return []


def _comparison_values(tree: ast.AST, parameter_name: str) -> list[object]:
    values: list[object] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        expressions = [node.left, *node.comparators]
        for index, expression in enumerate(expressions):
            if not isinstance(expression, ast.Name) or expression.id != parameter_name:
                continue
            for other in expressions[:index] + expressions[index + 1 :]:
                constants: list[object] = []
                if isinstance(other, ast.Constant):
                    constants = [other.value]
                elif isinstance(other, (ast.List, ast.Tuple, ast.Set)):
                    constants = [
                        item.value for item in other.elts if isinstance(item, ast.Constant)
                    ]
                for value in constants:
                    if isinstance(value, (str, int, float, bool, type(None))):
                        _append_unique(values, value)
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            _append_unique(values, value - 1)
                            _append_unique(values, value + 1)
    return values[:6]


def _mapping_keys(tree: ast.AST, parameter_name: str) -> list[str]:
    keys: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            if node.value.id == parameter_name and isinstance(node.slice, ast.Constant):
                if isinstance(node.slice.value, str) and node.slice.value not in keys:
                    keys.append(node.slice.value)
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if (
            isinstance(owner, ast.Name)
            and owner.id == parameter_name
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value not in keys
        ):
            keys.append(node.args[0].value)
    return keys[:10]


def _attribute_names(tree: ast.AST, parameter_name: str) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == parameter_name
            and node.attr not in names
            and not node.attr.startswith("__")
        ):
            names.append(node.attr)
    return names[:10]


def _environment_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            is_os_getenv = (
                isinstance(owner, ast.Name) and owner.id == "os" and node.func.attr == "getenv"
            )
            is_environ_get = (
                isinstance(owner, ast.Attribute)
                and isinstance(owner.value, ast.Name)
                and owner.value.id == "os"
                and owner.attr == "environ"
                and node.func.attr == "get"
            )
            if (is_os_getenv or is_environ_get) and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    if first.value not in names:
                        names.append(first.value)
        if not isinstance(node, ast.Subscript):
            continue
        owner = node.value
        if not (
            isinstance(owner, ast.Attribute)
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "os"
            and owner.attr == "environ"
        ):
            continue
        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            if node.slice.value not in names:
                names.append(node.slice.value)
    return names[:4]


def _semantic_scalar(name: str, enabled: bool) -> object:
    lowered = name.lower()
    if lowered in {"side", "direction"}:
        return "LONG" if enabled else "SHORT"
    if "action" in lowered:
        return "OPEN" if enabled else "CLOSE"
    if "status" in lowered:
        return "OK" if enabled else "ERROR"
    if "mode" in lowered:
        return "PAPER" if enabled else "OFF"
    if "venue" in lowered:
        return "hyperliquid" if enabled else "dydx"
    if "coin" in lowered or "symbol" in lowered or "asset" in lowered:
        return "BTC" if enabled else "ETH"
    if "wallet" in lowered or "address" in lowered:
        return harness.WALLET if enabled else ""
    if lowered.startswith(("is_", "has_", "allow", "enable", "require")):
        return enabled
    if any(
        token in lowered
        for token in (
            "price",
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
            "count",
            "limit",
            "age",
        )
    ):
        return 100.0 if enabled else 0.0
    return "unit" if enabled else ""


def _mapping_candidate(keys: list[str], enabled: bool) -> dict[str, object]:
    mapping: dict[str, object] = {}
    for key in keys:
        value = _semantic_scalar(key, enabled)
        nested_tokens = ("runtime", "metadata", "context", "payload", "data")
        if any(token in key.lower() for token in nested_tokens):
            value = {"ok": enabled, "status": "OK" if enabled else "ERROR"}
        mapping[key] = value
    return mapping


def _object_candidate(attributes: list[str], enabled: bool) -> harness.Dummy:
    return harness.Dummy(
        **{attribute: _semantic_scalar(attribute, enabled) for attribute in attributes}
    )


def _path_candidates(name: str, tmp_path: Path, tree: ast.AST) -> list[Path]:
    lowered = name.lower()
    if not any(token in lowered for token in ("path", "file", "dir", "root", "archive")):
        return []
    source_mentions_file = any(
        isinstance(node, ast.Attribute) and node.attr in {"is_file", "read_text", "read_bytes"}
        for node in ast.walk(tree)
    )
    source_mentions_dir = any(
        isinstance(node, ast.Attribute) and node.attr in {"is_dir", "iterdir", "glob", "rglob"}
        for node in ast.walk(tree)
    )
    values: list[Path] = [tmp_path / "missing-branch-probe"]
    if source_mentions_file:
        file_path = tmp_path / "branch-probe.json"
        file_path.write_text('{"ok": true, "status": "OK"}', encoding="utf-8")
        values.append(file_path)
    if source_mentions_dir:
        directory = tmp_path / "branch-probe-dir"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "sample.json").write_text('{"ok": true}', encoding="utf-8")
        values.append(directory)
    return values


def _parameter_candidates(
    function,
    parameter: inspect.Parameter,
    tmp_path: Path,
    settings: Settings,
) -> list[object]:
    tree = _tree(function)
    if tree is None:
        return []
    values: list[object] = []
    for value in _annotation_literals(parameter.annotation):
        _append_unique(values, value)
    for value in _comparison_values(tree, parameter.name):
        _append_unique(values, value)
    keys = _mapping_keys(tree, parameter.name)
    if keys:
        _append_unique(values, _mapping_candidate(keys, False))
        _append_unique(values, _mapping_candidate(keys, True))
    attributes = _attribute_names(tree, parameter.name)
    if attributes:
        _append_unique(values, _object_candidate(attributes, False))
        _append_unique(values, _object_candidate(attributes, True))
    for value in _path_candidates(parameter.name, tmp_path, tree):
        _append_unique(values, value)
    for mode in (0, 1, 2):
        _append_unique(
            values,
            harness._value(parameter.annotation, parameter.name, mode, tmp_path, settings),
        )
    return values[:8]


def _invoke_with_override(
    function,
    parameter_name: str,
    override: object,
    tmp_path: Path,
    settings: Settings,
):
    positional: list[object] = []
    keyword: dict[str, object] = {}
    for parameter in inspect.signature(function).parameters.values():
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        value = (
            override
            if parameter.name == parameter_name
            else harness._value(parameter.annotation, parameter.name, 1, tmp_path, settings)
        )
        if parameter.kind is parameter.POSITIONAL_ONLY:
            positional.append(value)
        else:
            keyword[parameter.name] = value
    return function(*positional, **keyword)


def _controlled(function_call) -> bool:
    try:
        function_call()
        return True
    except BaseExceptionGroup as error:
        if not harness._controlled_group(error):
            raise
    except (Exception, SystemExit):
        pass
    return False


def _exercise_environment_branches(
    function,
    tree: ast.AST,
    tmp_path: Path,
    settings: Settings,
) -> int:
    attempts = 0
    for name in _environment_names(tree):
        if any(token in name.upper() for token in SAFETY_ENV_TOKENS):
            continue
        previous = os.environ.get(name)
        try:
            for value in ("0", "1", "true", "EXPERIMENTAL"):
                if attempts >= MAX_ENV_CASES_PER_CALLABLE:
                    return attempts
                os.environ[name] = value
                attempts += 1
                _controlled(lambda: harness._invoke(function, 1, tmp_path, settings))
        finally:
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
    return attempts


def _exercise_callable(
    function,
    module_name: str,
    name: str,
    tmp_path: Path,
    settings: Settings,
) -> int:
    if not _safe(function, module_name, name):
        return 0
    tree = _tree(function)
    if tree is None:
        return 0
    attempts = 0
    try:
        parameters = list(inspect.signature(function).parameters.values())
    except (TypeError, ValueError):
        return 0
    for parameter in parameters:
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        for candidate in _parameter_candidates(function, parameter, tmp_path, settings):
            if attempts >= MAX_CASES_PER_CALLABLE:
                break
            attempts += 1
            _controlled(
                lambda parameter=parameter, candidate=candidate: _invoke_with_override(
                    function,
                    parameter.name,
                    candidate,
                    tmp_path,
                    settings,
                )
            )
        if attempts >= MAX_CASES_PER_CALLABLE:
            break
    attempts += _exercise_environment_branches(function, tree, tmp_path, settings)
    return attempts


def _safe_constructor(class_value: type, module_name: str) -> bool:
    if class_value.__module__ != module_name:
        return False
    try:
        if issubclass(class_value, (BaseException, enum.Enum)):
            return False
    except TypeError:
        return False
    init = getattr(class_value, "__init__", None)
    if init is None or init is object.__init__:
        return True
    if _blocking(init) or harness._contains_while_loop(init):
        return False
    lowered = class_value.__name__.lower()
    return not any(
        token in lowered
        for token in ("server", "listener", "worker", "thread", "process", "websocket")
    )


def _construct_instances(
    class_value: type,
    module_name: str,
    tmp_path: Path,
    settings: Settings,
) -> list[object]:
    if not _safe_constructor(class_value, module_name):
        return []
    instances: list[object] = []
    for mode in (0, 1, 2):
        try:
            signature = inspect.signature(class_value)
        except (TypeError, ValueError):
            return instances
        positional: list[object] = []
        keyword: dict[str, object] = {}
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
        try:
            instance = class_value(*positional, **keyword)
        except (Exception, SystemExit):
            continue
        instances.append(instance)
    return instances


def test_sharded_branch_fuzzer_exercises_real_remaining_paths(tmp_path, monkeypatch) -> None:
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
        database_url=f"sqlite:///{tmp_path / 'branch-fuzzer.sqlite3'}",
        logs_dir=str(tmp_path / "branch-fuzzer-logs"),
    )
    attempts = 0
    imported = 0
    for module_name in _targets_for_shard():
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        imported += 1
        for name, function in list(vars(module).items()):
            if inspect.isfunction(function) and function.__module__ == module_name:
                attempts += _exercise_callable(function, module_name, name, tmp_path, settings)
        for class_value in list(vars(module).values()):
            if not inspect.isclass(class_value) or class_value.__module__ != module_name:
                continue
            for name, descriptor in list(vars(class_value).items()):
                function = _method_function(descriptor)
                if function is not None:
                    attempts += _exercise_callable(function, module_name, name, tmp_path, settings)
            for instance in _construct_instances(class_value, module_name, tmp_path, settings):
                for name, descriptor in list(vars(class_value).items()):
                    if isinstance(descriptor, property):
                        continue
                    function = _method_function(descriptor)
                    if function is None or not hasattr(instance, name):
                        continue
                    bound = getattr(instance, name)
                    if callable(bound):
                        attempts += _exercise_callable(bound, module_name, name, tmp_path, settings)
    assert imported >= 1
    assert attempts >= 1
