"""[Bloc 25-28] Collecteurs supervises + resilience — machines d'etat REELLES, testables hors-ligne.

- SupervisedCollector : pid, heartbeat_ts, last_useful_event_ts, error_code, health() ->
  OK / STALE / NO_DATA / DEAD. AUD-384 : jamais SUCCESS si zero evenement UTILE. AUD-318/319 :
  liveness (heartbeat) != progression (last_useful_event_ts).
- ReconnectPolicy : backoff exponentiel borne (AUD-337).
- CircuitBreaker : closed/open/half-open par seuil d'echecs + cooldown (AUD-336).
- RateLimitCoordinator : token bucket GLOBAL multi-endpoint (AUD-335).
- BoundedQueue + load shedding par priorite (AUD-332/333) ; DiskQuota par source (AUD-334).

Le socket live reste hors-scope (REQUIRES_NETWORK) ; ici on PROUVE la logique de supervision/resilience.
Timestamps fournis par l'appelant (deterministe). stdlib pure, 0 reseau.
"""
from __future__ import annotations

import heapq
from typing import Optional

OK, STALE, NO_DATA, DEAD = "OK", "STALE", "NO_DATA", "DEAD"


class SupervisedCollector:
    def __init__(self, name: str, pid: int) -> None:
        self.name = name
        self.pid = int(pid)
        self.heartbeat_ts: Optional[float] = None
        self.last_useful_event_ts: Optional[float] = None
        self.n_useful = 0
        self.n_events = 0
        self.error_code: Optional[str] = None

    def battement(self, ts: float) -> None:
        self.heartbeat_ts = ts

    def evenement(self, ts: float, *, utile: bool) -> None:
        self.heartbeat_ts = ts
        self.n_events += 1
        if utile:
            self.n_useful += 1
            self.last_useful_event_ts = ts

    def erreur(self, code: str) -> None:
        self.error_code = code

    def health(self, maintenant: float, *, seuil_heartbeat_s: float, seuil_useful_s: float) -> str:
        if self.heartbeat_ts is None or (maintenant - self.heartbeat_ts) > seuil_heartbeat_s:
            return DEAD
        if self.n_useful == 0:
            return NO_DATA
        if self.last_useful_event_ts is None or (maintenant - self.last_useful_event_ts) > seuil_useful_s:
            return STALE
        return OK

    def est_success(self, maintenant: float, *, seuil_heartbeat_s: float, seuil_useful_s: float) -> bool:
        """AUD-384 : SUCCESS uniquement si health OK ET au moins un evenement utile. Jamais sur un
        simple heartbeat (marche calme != collecteur en bonne sante avec donnees)."""
        return self.n_useful > 0 and self.health(
            maintenant, seuil_heartbeat_s=seuil_heartbeat_s, seuil_useful_s=seuil_useful_s) == OK


class ReconnectPolicy:
    """Backoff exponentiel borne : delay(n) = min(cap, base * 2**n). Deterministe (pas de jitter)."""

    def __init__(self, base_s: float = 1.0, cap_s: float = 60.0) -> None:
        self.base_s = base_s
        self.cap_s = cap_s

    def delay(self, tentative: int) -> float:
        return min(self.cap_s, self.base_s * (2 ** max(0, tentative)))


class CircuitBreaker:
    """closed -> open apres `seuil` echecs consecutifs ; open -> half-open apres `cooldown_s` ;
    half-open -> closed sur succes, -> open sur echec (AUD-336)."""

    def __init__(self, seuil: int = 3, cooldown_s: float = 30.0) -> None:
        self.seuil = seuil
        self.cooldown_s = cooldown_s
        self.echecs = 0
        self.etat = "closed"
        self._ouvert_depuis: Optional[float] = None

    def echec(self, ts: float) -> None:
        if self.etat == "half":
            self.etat = "open"
            self._ouvert_depuis = ts
            return
        self.echecs += 1
        if self.echecs >= self.seuil:
            self.etat = "open"
            self._ouvert_depuis = ts

    def succes(self) -> None:
        self.echecs = 0
        self.etat = "closed"
        self._ouvert_depuis = None

    def autorise(self, ts: float) -> bool:
        if self.etat == "open":
            if self._ouvert_depuis is not None and (ts - self._ouvert_depuis) >= self.cooldown_s:
                self.etat = "half"
                return True
            return False
        return True


class RateLimitCoordinator:
    """Token bucket GLOBAL (capacite/fenetre) partage entre endpoints. acquire renvoie allowed."""

    def __init__(self, capacite: int, fenetre_s: float) -> None:
        self.capacite = capacite
        self.fenetre_s = fenetre_s
        self._events = []  # timestamps des acquisitions

    def acquire(self, ts: float) -> bool:
        self._events = [t for t in self._events if t > ts - self.fenetre_s]
        if len(self._events) < self.capacite:
            self._events.append(ts)
            return True
        return False


class BoundedQueue:
    """File bornee + load shedding : quand pleine, on JETTE l'element de plus BASSE priorite
    (priorite haute = nombre eleve). Retourne l'element eventuellement rejete (AUD-332/333)."""

    def __init__(self, maxlen: int) -> None:
        self.maxlen = maxlen
        self._h = []  # (priorite, seq, item)
        self._seq = 0

    def push(self, item, priorite: int = 0):
        self._seq += 1
        rejete = None
        if len(self._h) >= self.maxlen:
            pmin, s, it = min(self._h)
            if priorite <= pmin:
                return {"accepte": False, "rejete": item}
            self._h.remove((pmin, s, it))
            rejete = it
        heapq.heappush(self._h, (priorite, self._seq, item))
        return {"accepte": True, "rejete": rejete}

    def __len__(self):
        return len(self._h)


class DiskQuota:
    """Quota disque par source : add() refuse si depassement (AUD-334). Jamais silencieux."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.used = 0

    def add(self, nbytes: int) -> bool:
        if self.used + nbytes > self.max_bytes:
            return False
        self.used += nbytes
        return True
