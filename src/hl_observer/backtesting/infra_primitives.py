"""Primitives d'infrastructure — cœurs PURS, testés (le service externe n'est requis que pour les
brancher, pas pour les construire). Exécution du backlog :
TokenBucket (IDEA-38, rate limiter anti-ban), CircuitBreaker (IDEA-37, isolation d'une source
défaillante), exponential_backoff_with_jitter (IDEA-35, reconnexion WS), save/load_snapshot
(IDEA-36, reprise après crash), shard_assign (IDEA-39, répartition de la collecte). Aucun ordre.
"""
from __future__ import annotations

import hashlib
import json
import os
import random


class TokenBucket:
    """Rate limiter token-bucket : autorise des rafales bornées puis lisse le débit (anti-ban)."""

    def __init__(self, *, rate_per_sec: float, capacity: float):
        self.rate = float(rate_per_sec)
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.last = None

    def allow(self, now: float, cost: float = 1.0) -> bool:
        now = float(now)
        if self.last is None:
            self.last = now
        elapsed = max(0.0, now - self.last)
        self.last = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


class CircuitBreaker:
    """Coupe-circuit : après N échecs, bloque la source pendant `reset_after` secondes."""

    def __init__(self, *, fail_threshold: int = 3, reset_after: float = 10.0):
        self.fail_threshold = int(fail_threshold)
        self.reset_after = float(reset_after)
        self.fails = 0
        self.opened_at = None

    def allow(self, now: float) -> bool:
        if self.opened_at is None:
            return True
        if float(now) - self.opened_at >= self.reset_after:
            self.opened_at = None
            self.fails = 0
            return True
        return False

    def record_failure(self, now: float) -> None:
        self.fails += 1
        if self.fails >= self.fail_threshold:
            self.opened_at = float(now)

    def record_success(self) -> None:
        self.fails = 0
        self.opened_at = None


def exponential_backoff_with_jitter(attempt: int, *, base: float = 0.5, cap: float = 30.0,
                                    seed: int | None = None) -> float:
    """Délai de reconnexion : exponentiel plafonné + jitter complet (évite le troupeau synchronisé).

    BUG CORRIGÉ (fuzzing de l'audit, 2026-07-11) : `2 ** attempt` était calculé AVANT le
    plafonnement. Avec un compteur de tentatives qui dérape (run de 48 h, reconnexions en
    cascade), Python tentait de construire un entier gigantesque -> EXPLOSION MÉMOIRE, processus
    tué par l'OS. On borne désormais l'exposant AVANT de calculer la puissance.
    """
    try:
        a = int(attempt)
    except (TypeError, ValueError, OverflowError):
        a = 0
    a = max(0, min(a, 32))                      # 2**32 suffit largement : le cap tranche ensuite
    d = min(float(cap), float(base) * (2 ** a))
    rng = random.Random(seed)
    return rng.uniform(0.0, d)


def save_snapshot(path: str, state: dict) -> str:
    """Écrit un snapshot d'état de façon ATOMIQUE (tmp + replace) pour une reprise après crash."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, path)
    return path


def load_snapshot(path: str) -> dict:
    """Recharge un snapshot ; dict vide si absent/corrompu (état vide honnête, jamais inventé)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def shard_assign(key: str, n_shards: int) -> int:
    """Répartition STABLE d'une clé (coin) sur N shards de collecte (hash déterministe)."""
    if n_shards <= 1:
        return 0
    h = hashlib.md5(str(key).encode("utf-8")).hexdigest()
    return int(h, 16) % int(n_shards)
