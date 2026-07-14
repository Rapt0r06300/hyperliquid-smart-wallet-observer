"""Garde anti-lookahead (méta-test, IMPROVE-46). Vérifie qu'une fonction de signal n'utilise PAS le
futur : signal(series[:t+1])[t] doit égaler signal(series)[t]. Contrat : signal_fn(series) renvoie
une liste de MÊME longueur que l'entrée (None où indéfini). Aucun ordre, pur."""
from __future__ import annotations

import random


class LookaheadError(AssertionError):
    pass


def assert_no_lookahead(signal_fn, series, *, checks: int = 20, seed: int = 0, tol: float = 1e-9) -> bool:
    series = list(series)
    n = len(series)
    if n < 3:
        return True
    full = list(signal_fn(list(series)))
    if len(full) != n:
        raise LookaheadError(f"signal_fn doit renvoyer len={n}, a renvoyé len={len(full)}")
    rng = random.Random(seed)
    ts = sorted(set(rng.randrange(1, n) for _ in range(min(checks, n - 1))))
    for t in ts:
        prefix = list(signal_fn(list(series[:t + 1])))
        if len(prefix) != t + 1:
            raise LookaheadError(f"signal_fn(prefix) doit renvoyer len={t+1}, a renvoyé {len(prefix)}")
        a, b = prefix[t], full[t]
        if a is None or b is None:
            continue
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if abs(float(a) - float(b)) > tol:
                raise LookaheadError(f"lookahead à t={t}: {a} != {b} (le futur a changé le passé)")
        elif a != b:
            raise LookaheadError(f"lookahead à t={t}: {a} != {b}")
    return True
