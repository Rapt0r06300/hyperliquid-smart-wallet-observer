from __future__ import annotations

from types import SimpleNamespace

from hyper_smart_observer.dydx_v4.wallet_pool_ranker import wallet_pool_batch


def test_pool_batch_keeps_head_and_changes_tail() -> None:
    items = [SimpleNamespace(address=f"item{i}", score=float(1000 - i)) for i in range(100)]

    first = wallet_pool_batch(items, limit=20, scorer=lambda x: float(x.score), anchor_share=0.5)
    second = wallet_pool_batch(items, limit=20, scorer=lambda x: float(x.score), anchor_share=0.5)

    assert len(first) == 20
    assert len(second) == 20
    assert first[:10] == second[:10]
    assert first[10:] != second[10:]


def test_pool_batch_empty() -> None:
    assert wallet_pool_batch([], limit=20, scorer=lambda x: 1.0) == []
