from __future__ import annotations

from collections.abc import Callable
from functools import wraps


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


def _install_once(module, name: str, factory: Callable, marker: str) -> None:
    original = getattr(module, name, None)
    if not callable(original) or getattr(original, marker, False):
        return
    cached = factory(original)
    setattr(cached, marker, True)
    setattr(module, name, cached)


def pytest_configure(config) -> None:
    """Remove repeated static-analysis work from the real coverage contracts.

    No production callable, generated input, test case, branch, module, assertion,
    or coverage gate is skipped. Only immutable discovery/AST-analysis results are
    reused inside one pytest process; side-effectful candidate builders remain live.
    """
    del config
    from tests import test_coverage_closure_branch_fuzzer as base
    from tests import test_coverage_closure_branch_fuzzer_v2 as v2
    from tests import test_coverage_closure_dynamic_edges as dynamic

    for module in (dynamic, base, v2):
        _install_once(module, "_tree", _memoize_tree, "_coverage_ast_cached")
        _install_once(
            module,
            "_production_modules",
            _memoize_noarg,
            "_coverage_modules_cached",
        )

    # Base fuzzer: these helpers only inspect the immutable AST. They are called
    # repeatedly for every generated value of the same callable/parameter.
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

    # V2 performs deeper literal/pairwise analysis over the same AST. Cache only
    # the pure structural queries; actual invocations and generated candidates are
    # deliberately not cached so the measured execution remains identical.
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
