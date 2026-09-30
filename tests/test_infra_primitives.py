"""Tests des primitives d'infrastructure."""
from __future__ import annotations

from hl_observer.backtesting.infra_primitives import (
    CircuitBreaker,
    TokenBucket,
    exponential_backoff_with_jitter,
    load_snapshot,
    save_snapshot,
    shard_assign,
)


def test_token_bucket_bursts_then_throttles_then_refills():
    tb = TokenBucket(rate_per_sec=1.0, capacity=3.0)
    assert [tb.allow(0.0) for _ in range(3)] == [True, True, True]   # rafale = capacité
    assert tb.allow(0.0) is False                                     # épuisé
    assert tb.allow(2.0) is True                                      # 2s -> 2 jetons rechargés


def test_circuit_breaker_opens_and_resets():
    cb = CircuitBreaker(fail_threshold=3, reset_after=10.0)
    for t in range(3):
        cb.record_failure(float(t))
    assert cb.allow(3.0) is False        # ouvert après 3 échecs
    assert cb.allow(20.0) is True        # refermé après le délai
    cb.record_success()
    assert cb.allow(21.0) is True


def test_backoff_bounded_and_deterministic():
    a = exponential_backoff_with_jitter(5, base=0.5, cap=30.0, seed=1)
    b = exponential_backoff_with_jitter(5, base=0.5, cap=30.0, seed=1)
    assert a == b and 0.0 <= a <= 30.0


def test_snapshot_roundtrip_and_missing(tmp_path):
    p = str(tmp_path / "state.json")
    save_snapshot(p, {"poll": 42, "coin": "BTC"})
    assert load_snapshot(p) == {"poll": 42, "coin": "BTC"}
    assert load_snapshot(str(tmp_path / "absent.json")) == {}      # état vide honnête


def test_shard_assign_stable_and_spread():
    assert shard_assign("BTC", 4) == shard_assign("BTC", 4)         # stable
    shards = {shard_assign(c, 4) for c in ["BTC", "ETH", "SOL", "HYPE", "ZEC", "SUI"]}
    assert len(shards) > 1                                           # réparti sur plusieurs shards


def test_backoff_ne_explose_pas_la_memoire_sur_un_grand_compteur():
    """BUG REEL trouve par le fuzzing (2026-07-11) : `2 ** attempt` etait calcule AVANT le
    plafonnement -> un compteur qui derape faisait EXPLOSER la RAM (processus tue par l'OS).
    Ce test garantit que ca ne peut plus arriver."""
    from hl_observer.backtesting.infra_primitives import exponential_backoff_with_jitter
    for enorme in (10**6, 10**12, int(1e18)):
        d = exponential_backoff_with_jitter(enorme, base=0.5, cap=30.0, seed=1)
        assert 0.0 <= d <= 30.0, f"le delai doit rester borne par le cap, obtenu {d}"
