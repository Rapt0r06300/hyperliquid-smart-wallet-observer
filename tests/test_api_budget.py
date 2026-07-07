"""SCALE: budget API (token bucket + poids HL) → jamais de 429 en régime."""

from __future__ import annotations

from hl_observer.wallets.api_budget import ApiBudget, hl_request_weight


def test_hl_weight_formula():
    assert hl_request_weight() == 1
    assert hl_request_weight(batch_len=79) == 2          # 1 + floor(79/40)
    assert hl_request_weight(items_returned=60) == 4     # 1 + floor(60/20)
    assert hl_request_weight(batch_len=40, items_returned=40) == 4  # 1+1+2


def test_bucket_grants_until_empty_then_denies():
    b = ApiBudget(capacity=10, refill_per_sec=0)  # pas de refill pour le test
    now = 1000
    assert b.try_consume(6, now) is True
    assert b.try_consume(4, now) is True
    assert b.try_consume(1, now) is False   # bucket vide → refusé AVANT le 429
    assert b.stats()["denied"] == 1


def test_bucket_refills_over_time():
    b = ApiBudget(capacity=100, refill_per_sec=100)
    assert b.try_consume(100, 0) is True     # vide le bucket
    assert b.try_consume(50, 0) is False     # rien à t=0
    assert b.try_consume(50, 1000) is True   # +1s → +100 tokens → OK


def test_backoff_hint_and_user_rate_limit_sync():
    b = ApiBudget(capacity=100, refill_per_sec=50)
    b.try_consume(100, 0)
    wait = b.wait_ms_for(50, 0)
    assert wait == 1000.0    # 50 tokens manquants / 50 par sec = 1s
    # l'endpoint userRateLimit dit qu'il reste 80 → on s'aligne
    b.observe_user_rate_limit(remaining=80, capacity=200)
    assert b.stats()["tokens"] == 80.0 and b.stats()["capacity"] == 200.0
