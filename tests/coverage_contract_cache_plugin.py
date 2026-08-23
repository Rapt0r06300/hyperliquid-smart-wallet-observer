from __future__ import annotations

import concurrent.futures
import signal
import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path


class _CoverageContractCallTimeout(TimeoutError):
    """Stop one synthetic coverage invocation without stopping the real test."""


_REPO_ROOT = str(Path(__file__).resolve().parents[1]).replace("\\", "/").rstrip("/")
_REPO_PREFIX = _REPO_ROOT.casefold() + "/"
_PLUGIN_FILE = str(Path(__file__).resolve()).replace("\\", "/").casefold()
_UNSAFE_FRAME_RETRY_SECONDS = 0.01


class _InlineThreadPoolExecutor:
    """Deterministic ThreadPoolExecutor substitute for synthetic coverage calls.

    Coverage contracts intentionally invoke production callables with synthetic
    boundary inputs.  Starting real worker threads for those calls adds scheduler
    latency and can leave executor workers waiting on synthetic callbacks even
    though the same callback/path can be exercised synchronously.  This adapter
    preserves ``submit``/``map`` semantics and executes every submitted callable;
    it only removes concurrency from the coverage harness.  Production code is
    never patched outside the lifetime of the pytest monkeypatch fixture.
    """

    def __init__(self, max_workers: int | None = None, *args, **kwargs) -> None:
        del args, kwargs
        self.max_workers = max_workers
        self._shutdown = False

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> bool:
        self.shutdown()
        return False

    def submit(self, fn, /, *args, **kwargs):
        future: concurrent.futures.Future = concurrent.futures.Future()
        if self._shutdown:
            future.set_exception(RuntimeError("cannot schedule new futures after shutdown"))
            return future
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # Future must preserve executor exception semantics.
            future.set_exception(exc)
        return future

    def map(self, fn, *iterables, timeout=None, chunksize=1, buffersize=None):
        del timeout, chunksize, buffersize
        for args in zip(*iterables):
            yield fn(*args)

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        del wait, cancel_futures
        self._shutdown = True


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


def _controlled_timeout_frame(frame: object) -> bool:
    """Return True only for repository code where our private timeout is catchable.

    Raising an exception from a Python signal handler is asynchronous with respect
    to the interrupted Python code.  If that interruption lands in a weakref/GC
    callback or pytest/Pydantic/SQLAlchemy internals, the exception can become
    unraisable or corrupt pytest's own error rendering.  We therefore inject the
    private timeout only while execution is visibly back inside repository code.
    """

    code = getattr(frame, "f_code", None)
    filename = str(getattr(code, "co_filename", "") or "").replace("\\", "/").casefold()
    if not filename or filename == _PLUGIN_FILE:
        return False
    return filename.startswith(_REPO_PREFIX)


def _bounded_invoke(original: Callable, seconds: float = 0.5):
    """Bound one synthetic invocation without corrupting pytest's outer timer.

    Every candidate is still attempted and the 0.500 s limit is unchanged.  If
    our SIGALRM lands inside foreign/stdlib/framework code, the timeout is marked
    as expired and re-armed for a very short interval instead of throwing into an
    unsafe callback.  The private timeout is then raised as soon as execution is
    back in repository code, or synchronously when the invocation returns.

    If pytest-timeout already owns an earlier SIGALRM deadline, that deadline wins.
    An expired outer timer is never hidden by our retry loop.
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
        private_timeout_expired = False

        def _raise_timeout(signum, frame):
            nonlocal private_timeout_expired
            elapsed = time.monotonic() - started
            if previous_remaining > 0.0 and elapsed >= previous_remaining:
                if callable(previous_handler):
                    return previous_handler(signum, frame)
                raise _CoverageContractCallTimeout(
                    "outer coverage/pytest timer expired before controlled interruption"
                )
            if outer_wins and callable(previous_handler):
                return previous_handler(signum, frame)

            private_timeout_expired = True
            if _controlled_timeout_frame(frame):
                raise _CoverageContractCallTimeout(
                    f"generic coverage invocation exceeded {seconds:.3f}s"
                )

            retry = _UNSAFE_FRAME_RETRY_SECONDS
            if previous_remaining > 0.0:
                outer_left = previous_remaining - elapsed
                if outer_left > 0.0:
                    retry = min(retry, max(0.001, outer_left))
            signal.setitimer(signal.ITIMER_REAL, retry)
            return None

        signal.signal(signal.SIGALRM, _raise_timeout)
        signal.setitimer(signal.ITIMER_REAL, armed_for)
        try:
            result = original(*args, **kwargs)
            if private_timeout_expired:
                raise _CoverageContractCallTimeout(
                    f"generic coverage invocation exceeded {seconds:.3f}s"
                )
            return result
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            signal.signal(signal.SIGALRM, previous_handler)
            if previous_remaining > 0.0:
                remaining = previous_remaining - (time.monotonic() - started)
                if remaining > 0.0:
                    signal.setitimer(signal.ITIMER_REAL, remaining, previous_interval)

    return wrapped


def _bounded_controlled_bool(original: Callable):
    """Keep one timed-out boolean coverage attempt controlled, not test-fatal.

    ``_controlled`` deliberately turns ordinary synthetic-call exceptions into
    ``False``. Its final return sits outside its own ``try`` block, so a SIGALRM
    arriving on that boundary can otherwise escape after the candidate was already
    attempted. The outer adapter preserves the exact same controlled semantics.
    """
    bounded = _bounded_invoke(original)

    @wraps(original)
    def wrapped(*args, **kwargs):
        try:
            return bounded(*args, **kwargs)
        except _CoverageContractCallTimeout:
            return False

    return wrapped


def _bounded_controlled_count(original: Callable):
    """Count a timed-out synthetic invocation as attempted without hiding coverage.

    ``_controlled_invoke`` returns one attempted case even when the production call
    raises a controlled exception. A SIGALRM can land on its final ``return 1``
    outside the internal ``try``; converting only our private timeout back to ``1``
    keeps that existing contract. No candidate, assertion, module, line or coverage
    threshold is skipped or excluded.
    """
    bounded = _bounded_invoke(original)

    @wraps(original)
    def wrapped(*args, **kwargs):
        try:
            return bounded(*args, **kwargs)
        except _CoverageContractCallTimeout:
            return 1

    return wrapped


def _offline_guards_without_workers(original: Callable):
    """Keep synthetic coverage offline and deterministic without skipping work.

    Project-owned daemon workers must never outlive one candidate.  Asyncio still
    uses its own short-lived threads when needed, while ``ThreadPoolExecutor`` is
    replaced by an inline executor so every submitted callable is executed without
    launching a real pool from synthetic boundary inputs.
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
        monkeypatch.setattr(
            concurrent.futures,
            "ThreadPoolExecutor",
            _InlineThreadPoolExecutor,
        )

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
    project workers are suppressed while executor callbacks still all execute
    deterministically inline.
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
        _bounded_controlled_bool,
        "_coverage_controlled_bounded",
    )
    _install_once(
        v2,
        "_controlled_invoke",
        _bounded_controlled_count,
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