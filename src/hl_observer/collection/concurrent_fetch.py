"""Collecte plus rapide ET anti-ban (PERF).

Vérité mesurée: la limite Hyperliquid est un BUDGET DE POIDS PAR MINUTE
(1200/min/IP, cible sûre 840/min). Ce budget borne *combien de wallets on peut
poller par minute*, PAS la concurrence. La concurrence sert seulement à finir un
cycle plus vite (mur du temps), pas à dépasser le plafond.

Deux leviers honnêtes pour "scraper plus" sans ban:
  1) plus d'IP (proxies) -> multiplie le budget -> plus de wallets/min ;
  2) WS-first -> ce qui passe en push (userFills, allMids, trades) ne consomme
     PAS de poids REST, donc réserve le budget REST à ce que le WS ne donne pas.

Fonctions pures pour dimensionner; `bounded_gather` exécute en parallèle borné.
Aucune exécution réelle. Données publiques, lecture seule.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

HL_REST_WEIGHT_PER_MIN_PER_IP = 1200.0
DEFAULT_TARGET_WEIGHT_PER_MIN = 840.0   # marge sous 1200 pour absorber les pics


def max_calls_per_minute(
    *, weight_per_call: float, target_weight_per_min: float = DEFAULT_TARGET_WEIGHT_PER_MIN,
    num_egress_ips: int = 1,
) -> int:
    """Plafond RÉEL: nb d'appels REST/min qui reste sous le budget de poids."""
    weight_per_call = max(0.1, float(weight_per_call))
    budget = max(1.0, float(target_weight_per_min)) * max(1, int(num_egress_ips))
    return int(budget / weight_per_call)


def max_wallets_per_cycle(
    *, weight_per_call: float, calls_per_wallet: int, interval_s: float,
    target_weight_per_min: float = DEFAULT_TARGET_WEIGHT_PER_MIN, num_egress_ips: int = 1,
) -> int:
    """Combien de wallets on peut poller par cycle sans dépasser le budget/min.

    budget/min -> budget/cycle = budget/min * (interval/60). Chaque wallet coûte
    calls_per_wallet * weight_per_call. => wallets = budget_cycle / cout_wallet.
    C'est LA réponse honnête à "scraper plus": augmente interval, IP, ou passe en WS.
    """
    weight_per_call = max(0.1, float(weight_per_call))
    calls_per_wallet = max(1, int(calls_per_wallet))
    interval_s = max(1.0, float(interval_s))
    budget_per_min = max(1.0, float(target_weight_per_min)) * max(1, int(num_egress_ips))
    budget_per_cycle = budget_per_min * (interval_s / 60.0)
    cost_per_wallet = calls_per_wallet * weight_per_call
    return max(0, int(budget_per_cycle / cost_per_wallet))


def recommended_concurrency(
    *, num_tasks: int, avg_latency_s: float, deadline_s: float, hard_cap: int = 16,
) -> int:
    """Parallélisme pour finir `num_tasks` fetchs avant `deadline_s` (mur du temps).

    Série = num_tasks*latence. Pour tenir la deadline: workers >= tâches*latence/deadline.
    Borné par hard_cap. La sécurité anti-ban vient de max_wallets_per_cycle (le
    plafond de charge), pas d'ici — ici on optimise juste la latence du cycle.
    """
    num_tasks = max(0, int(num_tasks))
    if num_tasks == 0:
        return 1
    avg_latency_s = max(0.001, float(avg_latency_s))
    deadline_s = max(0.1, float(deadline_s))
    needed = math.ceil(num_tasks * avg_latency_s / deadline_s)
    return max(1, min(int(hard_cap), needed))


async def bounded_gather(
    factories: list[Callable[[], Awaitable[T]]], *, limit: int,
) -> list[T | BaseException]:
    """Exécute au plus `limit` coroutines en vol. Ordre préservé, exceptions isolées
    (un wallet en échec ne coupe pas le cycle)."""
    limit = max(1, int(limit))
    sem = asyncio.Semaphore(limit)
    results: list[T | BaseException] = [None] * len(factories)  # type: ignore[list-item]

    async def _run(i: int, factory: Callable[[], Awaitable[T]]) -> None:
        async with sem:
            try:
                results[i] = await factory()
            except BaseException as exc:  # noqa: BLE001
                results[i] = exc

    await asyncio.gather(*(_run(i, f) for i, f in enumerate(factories)))
    return results


__all__ = [
    "max_calls_per_minute", "max_wallets_per_cycle", "recommended_concurrency",
    "bounded_gather", "HL_REST_WEIGHT_PER_MIN_PER_IP", "DEFAULT_TARGET_WEIGHT_PER_MIN",
]
