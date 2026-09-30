from __future__ import annotations

import concurrent.futures
from collections.abc import Iterable

from hl_observer.research import parallel_factory


def _worker(shard: Iterable[int]) -> list[dict[str, int | str]]:
    return [
        {"trial_id": f"trial-{value}", "value": int(value)}
        for value in shard
    ]


class _InlineExecutor:
    calls: list[int | None] = []

    def __init__(self, max_workers: int | None = None) -> None:
        self.max_workers = max_workers
        type(self).calls.append(max_workers)

    def __enter__(self) -> _InlineExecutor:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def map(self, fn, *iterables):
        return map(fn, *iterables)


def test_parallel_factory_resout_thread_pool_depuis_concurrent_futures(monkeypatch) -> None:
    """Le garde-fou coverage doit pouvoir intercepter l'executor sans lancer de vrais threads."""

    _InlineExecutor.calls.clear()
    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", _InlineExecutor)

    result = parallel_factory.executer_parallele(
        [1, 2, 3, 4],
        _worker,
        n_workers=2,
        parallele=True,
    )

    assert _InlineExecutor.calls == [2]
    assert result == [
        {"trial_id": "trial-1", "value": 1},
        {"trial_id": "trial-2", "value": 2},
        {"trial_id": "trial-3", "value": 3},
        {"trial_id": "trial-4", "value": 4},
    ]
