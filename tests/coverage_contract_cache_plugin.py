from __future__ import annotations

from collections.abc import Callable
from functools import wraps


def _memoize_tree(original: Callable):
    """Memoize source ASTs without requiring bound methods to be hashable."""
    cache: dict[int, object] = {}

    @wraps(original)
    def wrapped(function):
        target = getattr(function, "__func__", function)
        key = id(target)
        if key not in cache:
            cache[key] = original(target)
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


def pytest_configure(config) -> None:
    """Remove repeated AST discovery work from the real coverage closure contracts.

    This plugin does not skip a callable, test case, branch, or production module.
    It only reuses immutable AST/module-discovery results inside one pytest process.
    """
    del config
    from tests import test_coverage_closure_branch_fuzzer as base
    from tests import test_coverage_closure_branch_fuzzer_v2 as v2
    from tests import test_coverage_closure_dynamic_edges as dynamic

    for module in (dynamic, base, v2):
        tree = getattr(module, "_tree", None)
        if callable(tree) and not getattr(tree, "_coverage_ast_cached", False):
            cached = _memoize_tree(tree)
            cached._coverage_ast_cached = True
            setattr(module, "_tree", cached)

        production_modules = getattr(module, "_production_modules", None)
        if callable(production_modules) and not getattr(
            production_modules, "_coverage_modules_cached", False
        ):
            cached_modules = _memoize_noarg(production_modules)
            cached_modules._coverage_modules_cached = True
            setattr(module, "_production_modules", cached_modules)
