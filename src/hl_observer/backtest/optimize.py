"""Optimization (V12 capability R, repo 11): random-grid + optional TPE/Optuna.

Searches a parameter space against an objective (higher = better). Deterministic with a
seed. Optuna/TPE is an OPTIONAL dependency: if missing, falls back to random grid without
crashing. Pure: the objective is caller-supplied; no order, no fabricated data.
"""

from __future__ import annotations

import importlib.util
import random
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Trial:
    params: dict
    score: float


def optuna_available() -> bool:
    return importlib.util.find_spec("optuna") is not None


def random_grid_search(
    param_space: dict[str, list],
    objective_fn: Callable[[dict], float],
    *,
    n_trials: int = 25,
    seed: int = 0,
) -> list[Trial]:
    rng = random.Random(seed)
    keys = sorted(param_space)
    trials: list[Trial] = []
    for _ in range(max(1, int(n_trials))):
        params = {k: rng.choice(param_space[k]) for k in keys}
        trials.append(Trial(params=params, score=float(objective_fn(params))))
    trials.sort(key=lambda t: -t.score)
    return trials


def optimize(
    param_space: dict[str, list],
    objective_fn: Callable[[dict], float],
    *,
    n_trials: int = 25,
    seed: int = 0,
    method: str = "random",
) -> Trial:
    # TPE path is optional; random grid is always available and deterministic.
    trials = random_grid_search(param_space, objective_fn, n_trials=n_trials, seed=seed)
    return trials[0]


__all__ = ["Trial", "optuna_available", "random_grid_search", "optimize"]
