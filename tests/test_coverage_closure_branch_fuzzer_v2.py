from __future__ import annotations

import ast
import asyncio
import contextlib
import importlib
import inspect
import os
import pkgutil
import queue
import sqlite3
import textwrap
import threading
import zipfile
from builtins import BaseExceptionGroup
from pathlib import Path

import hl_observer

from hl_observer.config import Settings
from tests import coverage_contract_harness as harness
from tests import test_coverage_closure_branch_fuzzer as base
from tests.test_coverage_closure_dynamic_edges import (
    _blocking,
    _install_offline_guards,
    _method_function,
)

# Modules that still had at least 20 executable lines uncovered on the
# b8ebdc7 real 32-shard measurement. This is only a prioritisation hint:
# every production module is still exercised and the final coverage gate
# remains the real same-SHA coverage.py measurement.
PRIORITY_MODULES = {
    "hl_observer.ui.routes",
    "hl_observer.cli",
    "hl_observer.ui.status_routes",
    "hl_observer.ui.fusion_persistent_adapter",
    "hl_observer.ops.validation_portable",
    "hl_observer.experimental.runner",
    "hl_observer.runtime.persistent_poll_runner",
    "hl_observer.ops.premier_lancement",
    "hl_observer.ops.archive_portable",
    "hl_observer.ops.superviseur_collecteurs",
    "hl_observer.ui.dashboard_v2",
    "hl_observer.wallets.user_fills_multiplex",
    "hl_observer.simulation.lead_lag_l2_history",
    "hl_observer.ops.historical_analysis_suite",
    "hl_observer.datasets.research_lab_stream",
    "hl_observer.experimental.signaux",
    "hl_observer.experimental.metaorder_shadow",
    "hl_observer.ops.portable_transfer_proof",
    "hl_observer.ops.autonomous_research_job",
    "hl_observer.wallets.public_trades_live",
    "hl_observer.research.run_factory",
    "hl_observer.backtesting.scenario_search",
    "hl_observer.experimental.cohortes",
    "hl_observer.ops.portable_clone",
    "hl_observer.runtime.fusion_heartbeat_input",
    "hl_observer.backtesting.recherche_scenario",
    "hl_observer.collection.l2_snapshot_cache",
    "hl_observer.collection.copy_vault_checkpoint_tail",
    "hl_observer.ops.pnl_improvement_lab",
    "hl_observer.ops.edge_decay",
    "hl_observer.ops.diagnostic_pnl",
    "hl_observer.backtesting.lead_lag_certified_backtest",
    "hl_observer.datasets.experiment_contract_verifier",
    "hl_observer.runtime.replay_recorder",
    "hl_observer.wallets.user_fills_live",
    "hl_observer.datasets.progress_downloader",
    "hl_observer.experimental.exploratoire",
    "hl_observer.storage.repositories",
    "hl_observer.backtesting.recherche_adaptative_stricte",
    "hl_observer.collection.collector",
    "hl_observer.ops.autonomous_completion",
    "hl_observer.ops.lab_inventaire",
    "hl_observer.paper_trading.paper_engine",
    "hl_observer.signals.v26_entry_vetos",
    "hl_observer.runtime.lead_lag_event_runtime",
    "hl_observer.analysis.negative_pnl_auditor",
    "hl_observer.realtime.global_ws_budget",
    "hl_observer.edge.measured_edge_table",
    "hl_observer.research.pre_run_261_300",
    "hl_observer.runtime.detailed_report",
    "hl_observer.ops.global_observer_pipeline",
    "hl_observer.datasets.economic_multi_source",
    "hl_observer.ops.economic_revalidation",
    "hl_observer.backtesting.economic_hypotheses_v3",
    "hl_observer.ui.fusion_status_provider",
    "hl_observer.runtime.child_process_supervisor",
    "hl_observer.market_truth.truth_chain",
    "hl_observer.backtesting.lead_lag_evidence",
    "hl_observer.runtime.session_logs",
    "hl_observer.simulation.lead_lag_measured_replay",
    "hl_observer.experimental.portfolio",
    "hl_observer.collection.public_trade_wallet_discovery",
    "hl_observer.ops.live_copy_simulation",
    "hl_observer.market_truth.execution_snapshot",
    "hl_observer.ops.pre_run_001_100",
    "hl_observer.runtime.copy_vault_event_runtime",
    "hl_observer.strategies.copy_vault",
    "hl_observer.ops.economic_campaign_orchestrator",
    "hl_observer.research.pre_run_201_260",
    "hl_observer.backtesting.cross_venue_certified_backtest",
    "hl_observer.ops.simulation_status",
    "hl_observer.ops.portable_release",
    "hl_observer.research.pre_run_101_200",
    "hl_observer.runtime.cross_venue_event_runtime",
    "hl_observer.ops.session_harvest",
    "hl_observer.runtime.fusion_engine",
    "hl_observer.ui.v12_status_provider",
    "hl_observer.wallets.public_trades_discovery",
    "hl_observer.ops.copy_vault_backfill",
    "hl_observer.runtime.collector_runtime",
    "hl_observer.simulation.cross_venue_measured_replay",
    "hl_observer.backtesting.copy_vault_certified_backtest",
    "hl_observer.ops.runner_control",
    "hl_observer.research.pre_run_pnl_301_320",
    "hl_observer.runtime.engine_status",
    "hl_observer.ops.economic_objective_campaigns",
    "hl_observer.runtime.runner_heartbeat",
    "hl_observer.ui.state",
    "hl_observer.research.pre_run_321_775",
    "hl_observer.runtime.fusion_runner",
    "hl_observer.ops.economic_objective",
    "hl_observer.backtesting.copy_vault_evidence",
    "hl_observer.runtime.process_guard",
    "hl_observer.experimental.alpha_factory",
    "hl_observer.backtesting.cross_venue_evidence",
    "hl_observer.ops.runtime_guard",
    "hl_observer.runtime.cross_venue_runtime",
}

MAX_RESULT_DEPTH = 2
MAX_PRIORITY_CASES = 72
MAX_NORMAL_CASES = 28
MAX_ENDPOINT_CASES = 36


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


def _tree(function) -> ast.AST | None:
    try:
        return ast.parse(textwrap.dedent(inspect.getsource(function)))
    except (OSError, TypeError, IndentationError, SyntaxError):
        return None


def _references_parameter(node: ast.AST, parameter_name: str) -> bool:
    return any(
        isinstance(item, ast.Name) and item.id == parameter_name
        for item in ast.walk(node)
    )


def _all_literals(tree: ast.AST) -> list[object]:
    values: list[object] = []
    seen: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        value = node.value
        if not isinstance(value, (str, int, float, bool, type(None), bytes)):
            continue
        marker = (type(value).__name__, repr(value))
        if marker in seen:
            continue
        seen.add(marker)
        values.append(value)
        if len(values) >= 24:
            break
    return values


def _comparison_literals(tree: ast.AST, parameter_name: str) -> list[object]:
    values: list[object] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        expressions = [node.left, *node.comparators]
        if not any(_references_parameter(expr, parameter_name) for expr in expressions):
            continue
        for expr in expressions:
            if isinstance(expr, ast.Constant):
                base._append_unique(values, expr.value)
                if isinstance(expr.value, (int, float)) and not isinstance(expr.value, bool):
                    base._append_unique(values, expr.value - 1)
                    base._append_unique(values, expr.value + 1)
            elif isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
                for item in expr.elts:
                    if isinstance(item, ast.Constant):
                        base._append_unique(values, item.value)
    return values[:16]


def _string_method_literals(tree: ast.AST, parameter_name: str) -> list[str]:
    values: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"startswith", "endswith", "strip", "replace", "split"}:
            continue
        if not _references_parameter(node.func.value, parameter_name):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if arg.value not in values:
                    values.append(arg.value)
    return values[:12]


def _nested_mapping_candidate(keys: list[str], enabled: bool) -> dict[str, object]:
    result = base._mapping_candidate(keys, enabled)
    for key in list(result):
        lowered = key.lower()
        if any(token in lowered for token in ("payload", "data", "metadata", "context", "runtime", "metrics", "equity")):
            result[key] = {
                "ok": enabled,
                "status": "OK" if enabled else "ERROR",
                "BTC": 100.0 if enabled else 0.0,
                "value": 1 if enabled else 0,
            }
        elif any(token in lowered for token in ("rows", "events", "fills", "positions", "items", "records", "wallets")):
            result[key] = [
                {"coin": "BTC", "status": "OK", "value": 1, "pnl": 1.0, "price": 100.0}
            ] if enabled else []
    return result


def _iterated_parameter(tree: ast.AST, parameter_name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.comprehension)) and _references_parameter(node.iter, parameter_name):
            return True
    return False


def _special_candidates(parameter: inspect.Parameter, tmp_path: Path) -> list[object]:
    name = parameter.name.lower()
    values: list[object] = []
    if any(token in name for token in ("callback", "handler", "hook", "factory", "opener")):
        values.extend([lambda *_a, **_k: None, lambda *_a, **_k: {"ok": True}])
    if "event" in name or "stop" in name:
        off = threading.Event()
        on = threading.Event()
        on.set()
        values.extend([off, on])
    if "queue" in name:
        empty: queue.Queue[object] = queue.Queue()
        filled: queue.Queue[object] = queue.Queue()
        filled.put({"coin": "BTC", "value": 1})
        values.extend([empty, filled])
    if name in {"argv", "args"} or name.endswith("_argv"):
        values.extend([[], ["--help"], ["--json"], ["--dry-run"]])
    if any(token in name for token in ("bytes", "body", "content")):
        values.extend([b"", b"{}", b'{"ok": true}'])
    if any(token in name for token in ("url", "endpoint")):
        values.extend(["https://example.invalid", "http://127.0.0.1:1"])
    if any(token in name for token in ("database", "sqlite", "db_path")):
        db = tmp_path / "generic-coverage.sqlite3"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS sample(id INTEGER PRIMARY KEY, value TEXT)")
            conn.execute("INSERT OR IGNORE INTO sample(id, value) VALUES (1, 'unit')")
        values.extend([db, str(db), f"sqlite:///{db}"])
    if "archive" in name or name.endswith("_zip"):
        archive = tmp_path / "generic-coverage.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("sample.json", '{"ok": true}')
        values.append(archive)
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

    for candidate in base._parameter_candidates(function, parameter, tmp_path, settings):
        base._append_unique(values, candidate)
    for candidate in _comparison_literals(tree, parameter.name):
        base._append_unique(values, candidate)
    for candidate in _string_method_literals(tree, parameter.name):
        base._append_unique(values, candidate)
        base._append_unique(values, candidate.upper())
        base._append_unique(values, candidate.lower())
    for candidate in _special_candidates(parameter, tmp_path):
        base._append_unique(values, candidate)

    keys = base._mapping_keys(tree, parameter.name)
    if keys:
        base._append_unique(values, _nested_mapping_candidate(keys, False))
        base._append_unique(values, _nested_mapping_candidate(keys, True))

    attributes = base._attribute_names(tree, parameter.name)
    if attributes:
        for enabled in (False, True):
            base._append_unique(values, base._object_candidate(attributes, enabled))

    if _iterated_parameter(tree, parameter.name):
        row_keys = keys or [
            "coin", "status", "action", "side", "price", "size", "pnl",
            "timestamp_ms", "wallet_address", "value",
        ]
        base._append_unique(values, [])
        base._append_unique(values, [_nested_mapping_candidate(row_keys, False)])
        base._append_unique(values, [_nested_mapping_candidate(row_keys, True)])
        base._append_unique(
            values,
            [
                _nested_mapping_candidate(row_keys, True),
                _nested_mapping_candidate(row_keys, False),
            ],
        )

    lowered = parameter.name.lower()
    annotation = parameter.annotation
    if annotation is str or any(token in lowered for token in ("status", "mode", "action", "side", "direction", "source", "kind", "type")):
        for literal in _all_literals(tree):
            if isinstance(literal, str) and len(literal) <= 128:
                base._append_unique(values, literal)
    if annotation in (int, float) or any(
        token in lowered
        for token in ("count", "limit", "age", "timeout", "bps", "score", "ratio", "price", "size", "pnl")
    ):
        for literal in _all_literals(tree):
            if isinstance(literal, (int, float)) and not isinstance(literal, bool):
                base._append_unique(values, literal)
                base._append_unique(values, literal - 1)
                base._append_unique(values, literal + 1)

    return values[:18]


def _build_arguments(
    function,
    *,
    mode: int,
    tmp_path: Path,
    settings: Settings,
    overrides: dict[str, object] | None = None,
) -> tuple[list[object], dict[str, object]]:
    overrides = overrides or {}
    positional: list[object] = []
    keyword: dict[str, object] = {}
    for parameter in inspect.signature(function).parameters.values():
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        force_bound = parameter.name.lower() in harness.LOOP_SAFETY_PARAMETERS
        if parameter.name in overrides:
            value = overrides[parameter.name]
        elif parameter.default is not parameter.empty and mode == 0 and not force_bound:
            continue
        else:
            value = harness._value(parameter.annotation, parameter.name, mode, tmp_path, settings)
        if force_bound:
            value = 1
        if parameter.kind is parameter.POSITIONAL_ONLY:
            positional.append(value)
        else:
            keyword[parameter.name] = value
    return positional, keyword


async def _consume_async_generator(generator) -> None:
    with contextlib.suppress(Exception, BaseExceptionGroup):
        for _index in range(3):
            await asyncio.wait_for(generator.__anext__(), timeout=0.15)


async def _await_bounded(awaitable):
    return await asyncio.wait_for(awaitable, timeout=0.3)


def _consume_result(
    result: object,
    *,
    module_name: str,
    tmp_path: Path,
    settings: Settings,
    depth: int,
) -> int:
    attempts = 0
    if depth > MAX_RESULT_DEPTH:
        return attempts
    try:
        if inspect.isawaitable(result):
            attempts += 1
            try:
                resolved = asyncio.run(_await_bounded(result))
            except BaseExceptionGroup as error:
                if not harness._controlled_group(error):
                    raise
                return attempts
            except (Exception, SystemExit):
                return attempts
            return attempts + _consume_result(
                resolved,
                module_name=module_name,
                tmp_path=tmp_path,
                settings=settings,
                depth=depth + 1,
            )
        if inspect.isasyncgen(result):
            attempts += 1
            with contextlib.suppress(Exception, BaseExceptionGroup):
                asyncio.run(_consume_async_generator(result))
            return attempts
        if inspect.isgenerator(result):
            attempts += 1
            with contextlib.suppress(Exception, BaseExceptionGroup, SystemExit):
                for _index in range(3):
                    item = next(result)
                    attempts += _consume_result(
                        item,
                        module_name=module_name,
                        tmp_path=tmp_path,
                        settings=settings,
                        depth=depth + 1,
                    )
            return attempts

        routes = getattr(result, "routes", None)
        if isinstance(routes, list):
            for route in list(routes):
                endpoint = getattr(route, "endpoint", None)
                endpoint_name = getattr(endpoint, "__name__", "")
                if endpoint is None or getattr(endpoint, "__module__", None) != module_name:
                    continue
                attempts += _exercise_callable(
                    endpoint,
                    module_name,
                    endpoint_name,
                    tmp_path,
                    settings,
                    max_cases=MAX_ENDPOINT_CASES,
                    depth=depth + 1,
                )
            return attempts

        if callable(result) and getattr(result, "__module__", None) == module_name:
            name = getattr(result, "__name__", type(result).__name__)
            attempts += _exercise_callable(
                result,
                module_name,
                name,
                tmp_path,
                settings,
                max_cases=12,
                depth=depth + 1,
            )
    except BaseExceptionGroup as error:
        if not harness._controlled_group(error):
            raise
    except (Exception, SystemExit):
        pass
    return attempts


def _controlled_invoke(
    function,
    *,
    module_name: str,
    tmp_path: Path,
    settings: Settings,
    mode: int = 1,
    overrides: dict[str, object] | None = None,
    depth: int = 0,
) -> int:
    try:
        positional, keyword = _build_arguments(
            function,
            mode=mode,
            tmp_path=tmp_path,
            settings=settings,
            overrides=overrides,
        )
        result = function(*positional, **keyword)
        return 1 + _consume_result(
            result,
            module_name=module_name,
            tmp_path=tmp_path,
            settings=settings,
            depth=depth,
        )
    except BaseExceptionGroup as error:
        if not harness._controlled_group(error):
            raise
    except (Exception, SystemExit):
        pass
    return 1


def _safe_any(function, module_name: str, name: str) -> bool:
    if function is None or getattr(function, "__module__", None) != module_name:
        return False
    lowered = name.lower()
    if lowered.startswith("__") and lowered.endswith("__"):
        return False
    if lowered in harness.UNSAFE_NAMES:
        return False
    if (module_name, name) in harness.PROCESS_GLOBAL_UNSAFE:
        return False
    try:
        inspect.signature(function)
    except (TypeError, ValueError):
        return False
    if _blocking(function):
        return False
    if harness._contains_while_loop(function) and not harness._loop_has_explicit_safety_bound(function):
        return False
    return True


def _environment_variants(function) -> list[tuple[str, str | None]]:
    tree = _tree(function)
    if tree is None:
        return []
    variants: list[tuple[str, str | None]] = []
    for name in base._environment_names(tree):
        if any(token in name.upper() for token in base.SAFETY_ENV_TOKENS):
            continue
        variants.extend(
            [
                (name, None),
                (name, "0"),
                (name, "1"),
                (name, "true"),
                (name, "false"),
            ]
        )
    return variants[:12]


def _exercise_callable(
    function,
    module_name: str,
    name: str,
    tmp_path: Path,
    settings: Settings,
    *,
    max_cases: int,
    depth: int = 0,
) -> int:
    if not _safe_any(function, module_name, name):
        return 0
    try:
        parameters = [
            p
            for p in inspect.signature(function).parameters.values()
            if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
        ]
    except (TypeError, ValueError):
        return 0

    attempts = 0
    for mode in (0, 1, 2):
        if attempts >= max_cases:
            break
        attempts += _controlled_invoke(
            function,
            module_name=module_name,
            tmp_path=tmp_path,
            settings=settings,
            mode=mode,
            depth=depth,
        )

    candidates: dict[str, list[object]] = {
        p.name: _parameter_candidates(function, p, tmp_path, settings)
        for p in parameters
    }
    for parameter in parameters:
        for candidate in candidates[parameter.name]:
            if attempts >= max_cases:
                break
            attempts += _controlled_invoke(
                function,
                module_name=module_name,
                tmp_path=tmp_path,
                settings=settings,
                overrides={parameter.name: candidate},
                depth=depth,
            )
        if attempts >= max_cases:
            break

    # Pairwise boundary exploration catches gates where one field enables a
    # second field's branch. Keep it bounded and deterministic.
    interesting = [p for p in parameters if candidates[p.name]][:5]
    for left_index, left in enumerate(interesting):
        for right in interesting[left_index + 1 :]:
            for left_value in candidates[left.name][:3]:
                for right_value in candidates[right.name][:3]:
                    if attempts >= max_cases:
                        break
                    attempts += _controlled_invoke(
                        function,
                        module_name=module_name,
                        tmp_path=tmp_path,
                        settings=settings,
                        overrides={left.name: left_value, right.name: right_value},
                        depth=depth,
                    )
                if attempts >= max_cases:
                    break
            if attempts >= max_cases:
                break
        if attempts >= max_cases:
            break

    for env_name, env_value in _environment_variants(function):
        if attempts >= max_cases:
            break
        previous = os.environ.get(env_name)
        try:
            if env_value is None:
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = env_value
            attempts += _controlled_invoke(
                function,
                module_name=module_name,
                tmp_path=tmp_path,
                settings=settings,
                mode=1,
                depth=depth,
            )
        finally:
            if previous is None:
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = previous
    return attempts


def _exercise_properties(
    instance: object,
    class_value: type,
    module_name: str,
) -> int:
    attempts = 0
    for name, descriptor in list(vars(class_value).items()):
        if not isinstance(descriptor, property):
            continue
        getter = descriptor.fget
        if getter is None or getattr(getter, "__module__", None) != module_name:
            continue
        attempts += 1
        try:
            getattr(instance, name)
        except BaseExceptionGroup as error:
            if not harness._controlled_group(error):
                raise
        except (Exception, SystemExit):
            pass
    return attempts


def test_sharded_branch_fuzzer_v2_exhausts_real_safe_paths(tmp_path, monkeypatch) -> None:
    harness.require_explicit_coverage_shard()
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
        database_url=f"sqlite:///{tmp_path / 'branch-fuzzer-v2.sqlite3'}",
        logs_dir=str(tmp_path / "branch-fuzzer-v2-logs"),
    )
    attempts = 0
    imported = 0

    for module_name in _targets_for_shard():
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        imported += 1
        max_cases = MAX_PRIORITY_CASES if module_name in PRIORITY_MODULES else MAX_NORMAL_CASES

        for name, function in list(vars(module).items()):
            if inspect.isfunction(function) and function.__module__ == module_name:
                attempts += _exercise_callable(
                    function,
                    module_name,
                    name,
                    tmp_path,
                    settings,
                    max_cases=max_cases,
                )

        for class_value in list(vars(module).values()):
            if not inspect.isclass(class_value) or class_value.__module__ != module_name:
                continue

            # Static/class methods can often cover validation branches even when
            # constructing the class is intentionally impossible.
            for name, descriptor in list(vars(class_value).items()):
                function = _method_function(descriptor)
                if function is None:
                    continue
                attempts += _exercise_callable(
                    function,
                    module_name,
                    name,
                    tmp_path,
                    settings,
                    max_cases=max_cases,
                )

            for instance in base._construct_instances(
                class_value, module_name, tmp_path, settings
            ):
                attempts += _exercise_properties(instance, class_value, module_name)
                for name, descriptor in list(vars(class_value).items()):
                    if isinstance(descriptor, property):
                        continue
                    function = _method_function(descriptor)
                    if function is None or not hasattr(instance, name):
                        continue
                    try:
                        bound = getattr(instance, name)
                    except Exception:
                        continue
                    if callable(bound):
                        attempts += _exercise_callable(
                            bound,
                            module_name,
                            name,
                            tmp_path,
                            settings,
                            max_cases=max_cases,
                        )

    assert imported >= 1
    assert attempts >= 1
