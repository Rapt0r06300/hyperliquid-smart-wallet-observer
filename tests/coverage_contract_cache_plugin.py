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
    """Bound one generic invocation while preserving pytest-timeout's deadline.

    Every synthetic call is still attempted. A call that blocks in a wait/join or
    an opaque library boundary is interrupted after a short POSIX deadline. The
    pre-existing SIGALRM timer is restored with elapsed wall time subtracted, so
    this helper never extends the outer pytest timeout.
    """
    if not hasattr(signal, "setitimer"):
        return original

    @wraps(original)
    def wrapped(*args, **kwargs):
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_remaining, previous_interval = signal.getitimer(signal.ITIMER_REAL)
        started = time.monotonic()

        def _raise_timeout(_signum, _frame):
            raise _CoverageContractCallTimeout(
                f"generic coverage invocation exceeded {seconds:.3f}s"
            )

        signal.signal(signal.SIGALRM, _raise_timeout)
        signal.setitimer(signal.ITIMER_REAL, seconds)
        try:
            return original(*args, **kwargs)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            signal.signal(signal.SIGALRM, previous_handler)
            if previous_remaining > 0.0:
                elapsed = time.monotonic() - started
                remaining = max(1e-6, previous_remaining - elapsed)
                signal.setitimer(signal.ITIMER_REAL, remaining, previous_interval)

    return wrapped


def _install_once(module, name: str, factory: Callable, marker: str) -> None:
    original = getattr(module, name, None)
    if not callable(original) or getattr(original, marker, False):
        return
    cached = factory(original)
    setattr(cached, marker, True)
    setattr(module, name, cached)


def pytest_configure(config) -> None:
    """Cache static analysis and bound all generic synthetic coverage invocations.

    No production callable, generated input, test case, branch, module, assertion,
    or coverage gate is skipped. Only immutable analysis is cached; every execution
    candidate is still attempted under a per-call deadline.
    """
    del config
    from tests import coverage_contract_harness as harness
    from tests import test_coverage_closure_branch_fuzzer as base
    from tests import test_coverage_closure_branch_fuzzer_v2 as v2
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
