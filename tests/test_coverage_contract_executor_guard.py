from __future__ import annotations

import concurrent.futures
import threading

import pytest

from tests.coverage_contract_cache_plugin import _offline_guards_without_workers


def test_coverage_offline_guard_executes_every_executor_callback_inline(monkeypatch) -> None:
    """Le fuzzer garde tous les callbacks sans créer de vrais workers."""

    starts: list[str] = []

    def forbidden_thread_start(thread: threading.Thread):
        starts.append(str(thread.name))
        raise AssertionError(f"unexpected real coverage worker: {thread.name}")

    monkeypatch.setattr(threading.Thread, "start", forbidden_thread_start)
    guarded = _offline_guards_without_workers(lambda _monkeypatch: None)
    guarded(monkeypatch)

    caller_thread = threading.get_ident()
    callbacks: list[int] = []

    def worker(value: int) -> tuple[int, int]:
        callbacks.append(value)
        return value * 2, threading.get_ident()

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        mapped = list(executor.map(worker, range(6)))
        submitted = executor.submit(worker, 6)

    assert callbacks == [0, 1, 2, 3, 4, 5, 6]
    assert [value for value, _thread_id in mapped] == [0, 2, 4, 6, 8, 10]
    assert submitted.result() == (12, caller_thread)
    assert all(thread_id == caller_thread for _value, thread_id in mapped)
    assert starts == []


def test_coverage_inline_executor_preserves_callback_exceptions(monkeypatch) -> None:
    guarded = _offline_guards_without_workers(lambda _monkeypatch: None)
    guarded(monkeypatch)

    def explode() -> None:
        raise ValueError("synthetic callback failure")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future = executor.submit(explode)

    with pytest.raises(ValueError, match="synthetic callback failure"):
        future.result()
