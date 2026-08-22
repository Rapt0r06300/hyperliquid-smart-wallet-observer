from __future__ import annotations

import signal
import time
from collections.abc import Callable
from functools import wraps


class _CoverageContractCallTimeout(TimeoutError):
    """Stop one synthetic coverage invocation without stopping the real test."""


def _target_id(value: object) -> int:
    """Stable in-process identity for functions and bound methods."""
    return id(getattr(value, "__func__", value))


def _memoize_tree(original: Callable):
    """Memoize source ASTs without requiring bound methods to be hashable."""
    cache: dict[int, object] = {}

    @wraps(original)
    def wrapped(function):
        key = _target_id(function)
        if key not in cache:
            cache[key] = original(getattr(function, "__func__", function))
        return cache[key]

    return wrapped


def _memoize_noarg(original: Callable):
    cache: list[object] = []

    @wraps(original)
    def wrapped():
        if not cache:
            cache.append(original())
        return cache[0]

    return wrapped


def _memoize_tree_only(original: Callable):
    """Cache a pure AST analysis helper taking only the tree."""
    cache: dict[int, object] = {}

    @wraps(original)
    def wrapped(tree):
        key = id(tree)
        if key not in cache:
            cache[key] = original(tree)
        return cache[key]

    return wrapped


def _memoize_tree_parameter(original: Callable):
    """Cache pure AST analyses keyed by AST identity and parameter name."""
    cache: dict[tuple[int, str], object] = {}

    @wraps(original)
    def wrapped(tree, parameter_name):
        key = (id(tree), str(parameter_name))
        if key not in cache:
            cache[key] = original(tree, parameter_name)
        return cache[key]

    return wrapped


def _memoize_function_only(original: Callable):
    """Cache a pure helper whose only input is a callable."""
    cache: dict[int, object] = {}

    @wraps(original)
    def wrapped(function):
        key = _target_id(function)
        if key not in cache:
            cache[key] = original(function)
        return cache[key]

    return wrapped


def _bounded_invoke(original: Callable, seconds: float = 0.5):
    """Bound one synthetic invocation without corrupting pytest's outer timer.

    Every candidate is still attempted. If pytest-timeout already owns an earlier
    SIGALRM deadline, that deadline wins. An expired outer timer is never re-armed
    with a tiny residual value, which avoids stray SIGALRM during coverage teardown.
    """
    if not hasattr(signal, "setitimer"):
        return original

    @wraps(original)
    def wrapped(*args, **kwargs):
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_remaining, previous_interval = signal.getitimer(signal.ITIMER_REAL)
        started = time.monotonic()
        outer_wins = previous_remaining > 0.0 and previous_remaining <= seconds
        armed_for = previous_remaining if outer_wins else seconds

        def _raise_timeout(signum, frame):
            if outer_wins and callable(previous_handler):
                return previous_handler(signum, frame)
            raise _CoverageContractCallTimeout(
                f"generic coverage invocation exceeded {seconds:.3f}s"
            )

        signal.signal(signal.SIGALRM, _raise_timeout)
        signal.setitimer(signal.ITIMER_REAL, armed_for)
        try:
            return original(*args, **kwargs)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            signal.signal(signal.SIGALRM, previous_handler)
            if previous_remaining > 0.0:
                remaining = previous_remaining - (time.monotonic() - started)
                if remaining > 0.0:
                    signal.setitimer(signal.ITIMER_REAL, remaining, previous_interval)

    return wrapped


def _offline_guards_without_workers(original: Callable):
    """Prevent persistent HyperSmart workers without breaking Python executors.

    The synthetic closure tests may reach production startup paths that create
    daemon workers. Those project-owned workers must not outlive one candidate,
    but asyncio and concurrent-futures need their own short-lived threads to start
    and join normally. Guard only threads explicitly named ``hypersmart-*``.
    """

    @wraps(original)
    def wrapped(monkeypatch):
        original(monkeypatch)
        import threading

        original_start = threading.Thread.start
        original_join = threading.Thread.join

        def _is_hypersmart_worker(thread: threading.Thread) -> bool:
            return str(getattr(thread, "name", "")).lower().startswith("hypersmart-")

        def _start(thread: threading.Thread):
            if _is_hypersmart_worker(thread):
                return None
            return original_start(thread)

        def _join(thread: threading.Thread, *args, **kwargs):
            if _is_hypersmart_worker(thread):
                return None
            return original_join(thread, *args, **kwargs)

        monkeypatch.setattr(threading.Thread, "start", _start)
        monkeypatch.setattr(threading.Thread, "join", _join)

    return wrapped


def _install_once(module, name: str, factory: Callable, marker: str) -> None:
    original = getattr(module, name, None)
    if not callable(original) or getattr(original, marker, False):
        return
    cached = factory(original)
    setattr(cached, marker, True)
    setattr(module, name, cached)


def pytest_configure(config) -> None:
    """Cache static analysis and bound generic synthetic coverage invocations.

    No production callable, generated input, test case, branch, module, assertion,
    or coverage gate is skipped. Immutable analysis is cached and persistent
    project workers are suppressed while standard Python executors remain intact.
    """
    del config
    from tests import coverage_contract_harness as harness
    from tests import test_coverage_closure_branch_fuzzer as base
    from tests import test_coverage_closure_branch_fuzzer_v2 as v2
    from tests import test_coverage_closure_closure_fuzzer as closure
    from tests import test_coverage_closure_dynamic_edges as dynamic

    _install_once(
        harness,
        "_invoke",
        _bounded_invoke,
        "_coverage_invocation_bounded",
    )
    _install_once(
        base,
        "_controlled",
        _bounded_invoke,
        "_coverage_controlled_bounded",
    )
    _install_once(
        v2,
        "_controlled_invoke",
        _bounded_invoke,
        "_coverage_controlled_invoke_bounded",
    )

    for module in (dynamic, base, v2, closure):
        _install_once(
            module,
            "_install_offline_guards",
            _offline_guards_without_workers,
            "_coverage_offline_workers_guarded",
        )

    for module in (dynamic, base, v2):
        _install_once(module, "_tree", _memoize_tree, "_coverage_ast_cached")
        _install_once(
            module,
            "_production_modules",
            _memoize_noarg,
            "_coverage_modules_cached",
        )

    for helper in (
        "_comparison_values",
        "_mapping_keys",
        "_attribute_names",
    ):
        _install_once(
            base,
            helper,
            _memoize_tree_parameter,
            f"_coverage_cached_{helper}",
        )
    _install_once(
        base,
        "_environment_names",
        _memoize_tree_only,
        "_coverage_cached_environment_names",
    )

    for helper in (
        "_comparison_literals",
        "_string_method_literals",
        "_iterated_parameter",
    ):
        _install_once(
            v2,
            helper,
            _memoize_tree_parameter,
            f"_coverage_cached_{helper}",
        )
    _install_once(
        v2,
        "_all_literals",
        _memoize_tree_only,
        "_coverage_cached_all_literals",
    )
    _install_once(
        v2,
        "_environment_variants",
        _memoize_function_only,
        "_coverage_cached_environment_variants",
    )
