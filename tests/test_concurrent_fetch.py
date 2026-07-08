"""Contrat PERF collecte: plafond anti-ban correct + parallélisme borné."""

from __future__ import annotations

import asyncio
import time

from hl_observer.collection.concurrent_fetch import (
    bounded_gather,
    max_calls_per_minute,
    max_wallets_per_cycle,
    recommended_concurrency,
)


def test_max_calls_per_minute_respects_weight_budget():
    # 20 poids/appel, cible 840/min, 1 IP -> 42 appels/min
    assert max_calls_per_minute(weight_per_call=20.0, target_weight_per_min=840.0, num_egress_ips=1) == 42
    # proxies = multiplie le plafond (le VRAI levier anti-ban pour scraper plus)
    assert max_calls_per_minute(weight_per_call=20.0, target_weight_per_min=840.0, num_egress_ips=5) == 210


def test_max_wallets_per_cycle_exposes_the_real_ceiling():
    # 20 poids, 3 appels/wallet, cycle 15s, 840/min, 1 IP -> budget/cycle=210, cout=60 -> 3 wallets
    w = max_wallets_per_cycle(weight_per_call=20.0, calls_per_wallet=3, interval_s=15.0, num_egress_ips=1)
    assert w == 3                                        # 50 leaders/15s dépasserait 16x le budget !
    # leviers honnêtes: plus d'IP, cycle plus long, ou WS (moins d'appels REST/wallet)
    assert max_wallets_per_cycle(weight_per_call=20.0, calls_per_wallet=3, interval_s=15.0, num_egress_ips=5) == 17
    assert max_wallets_per_cycle(weight_per_call=20.0, calls_per_wallet=1, interval_s=60.0, num_egress_ips=1) == 42


def test_recommended_concurrency_meets_deadline_and_caps():
    # 50 fetchs de 0.3s à finir en 7.5s -> ceil(50*0.3/7.5)=2 workers
    assert recommended_concurrency(num_tasks=50, avg_latency_s=0.3, deadline_s=7.5) == 2
    assert recommended_concurrency(num_tasks=0, avg_latency_s=0.3, deadline_s=7.5) == 1     # rien à faire
    assert recommended_concurrency(num_tasks=10_000, avg_latency_s=1.0, deadline_s=0.5, hard_cap=16) == 16


def test_bounded_gather_parallel_ordered_isolated():
    async def _go():
        def make(i, boom=False):
            async def _t():
                await asyncio.sleep(0.05)
                if boom:
                    raise ValueError(i)
                return i * 10
            return _t

        t0 = time.perf_counter()
        res = await bounded_gather([make(i, boom=(i == 3)) for i in range(10)], limit=5)
        return res, time.perf_counter() - t0

    res, dt = asyncio.run(_go())
    assert res[0] == 0 and res[9] == 90                  # ordre préservé
    assert isinstance(res[3], ValueError)                # échec isolé, cycle non coupé
    assert dt < 0.35                                     # 10x50ms en //5 ~0.1s (série=0.5s)


def test_bounded_gather_never_exceeds_limit():
    async def _go():
        live = {"cur": 0, "peak": 0}

        def make():
            async def _t():
                live["cur"] += 1
                live["peak"] = max(live["peak"], live["cur"])
                await asyncio.sleep(0.02)
                live["cur"] -= 1
            return _t

        await bounded_gather([make() for _ in range(20)], limit=4)
        return live["peak"]

    assert asyncio.run(_go()) <= 4
