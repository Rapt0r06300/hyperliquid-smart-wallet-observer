"""QUEUE BORNÉE — ne JAMAIS perdre un fill en silence (2026-07-11). Phase 5 du brief.

⚠️⚠️ CORRECTION DU 2026-07-13 — CE FICHIER ACCUSAIT LA PRODUCTION A TORT. LIRE AVANT DE CROIRE.
================================================================================================
La version d'origine de cet en-tete affirmait que la queue vivante
(`realtime/low_latency_event_queue.py`) **jetait des `userFill` en silence**. **C'est FAUX**, et je
l'ai verifie par lecture du seul appelant reel (T3e, 2026-07-13) :

    strategies/fusion_runtime.py:167
        queue = LowLatencyEventQueue(max_size=2_000)
        for event in payload.price_events:      # <- UNIQUEMENT des PriceEvent
            queue.push(...)
        ... = queue.drain()                     # <- drainee IMMEDIATEMENT, dans le meme appel

Cette queue est un **tampon de TRI par horodatage**, cree et vide dans un seul appel de fonction.
Elle ne voit **JAMAIS** un `userFill`, ni une ouverture/fermeture de leader. Elle ne peut donc pas
commettre la faute qu'on lui reprochait ici.

Le defaut de `heappop()` (jeter le plus ancien) reste **reel mais LATENT** : il ne se declenche
qu'au-dela de 2 000 `PriceEvent` dans un seul appel, et ce qu'il jetterait alors, ce sont des
snapshots de prix -- precisement ce que la taxonomie ci-dessous classe **COALESCABLE** (seul le
dernier compte) et que `merge_price_events()` fusionne de toute facon juste apres.

> 🚩 **La lecon est pour moi.** J'ai ecrit une accusation plausible sans lire l'appelant, puis je
> l'ai laissee servir de justification a un module... que personne n'a jamais branche. C'est
> exactement le piege **X-06** (« verifier les AFFIRMATIONS avant le code »), applique a mon propre
> code. *Un module qui se justifie par un bug qui n'existe pas est deux fois mort.*

Ce module reste **JUSTE dans sa taxonomie** (la regle ci-dessous est bonne) et **NON BRANCHE** :
il attend un vrai consommateur de flux temps reel. Il est declare mort dans
`runtime/tombstones_runtime.py`, avec cette raison. Voir T3e / tache #593.
================================================================================================

CE MODULE POSE LA REGLE :

    JAMAIS_JETABLE   userFill, ouverture/reduction/fermeture leader
                     -> sous surcharge, on NE LES JETTE PAS. On declare BACKPRESSURE.
    COALESCABLE      allMids, bbo, snapshots de prix
                     -> seul le DERNIER etat compte : les intermediaires peuvent fusionner.
    JETABLE          le reste, et uniquement en dernier recours -- toujours COMPTE et VISIBLE.

Un drop silencieux est un signal qu'on ne verra JAMAIS, et une perte qu'on n'expliquera jamais.

PUR, sans I/O. Aucun ordre reel.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque

# --- classes d'evenements. La classe DECIDE du sort de l'evenement sous surcharge.
JAMAIS_JETABLE = "NEVER_DROP"
COALESCABLE = "COALESCE_LAST_WINS"
JETABLE = "DROPPABLE"

# Ces types sont irremplacables : les perdre, c'est perdre le signal lui-meme.
TYPES_JAMAIS_JETABLES = frozenset({
    "userFill", "user_fill", "fill",
    "leader_open", "leader_add", "leader_reduce", "leader_close",
})
# Ceux-la : seul le dernier etat a une valeur. Garder les intermediaires ne sert a rien.
TYPES_COALESCABLES = frozenset({"allMids", "bbo", "mid", "price_snapshot"})


def classer(event_type: str) -> str:
    t = str(event_type or "")
    if t in TYPES_JAMAIS_JETABLES:
        return JAMAIS_JETABLE
    if t in TYPES_COALESCABLES:
        return COALESCABLE
    return JETABLE


@dataclass(frozen=True, slots=True)
class Event:
    event_id: str
    event_type: str
    event_time_ms: int
    payload: dict[str, Any] = field(default_factory=dict)
    # cle de coalescence : pour un snapshot de prix, c'est le coin (seul le dernier compte)
    coalesce_key: str = ""


@dataclass(slots=True)
class QueueMetrics:
    recus: int = 0
    traites: int = 0
    jetes: int = 0
    coalesces: int = 0
    doublons: int = 0
    hors_ordre: int = 0
    # LE compteur qui doit rester a ZERO. S'il bouge, un signal a ete perdu.
    jamais_jetables_perdus: int = 0
    backpressure_events: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "recus": self.recus, "traites": self.traites,
            "jetes": self.jetes, "coalesces": self.coalesces,
            "doublons": self.doublons, "hors_ordre": self.hors_ordre,
            "jamais_jetables_perdus": self.jamais_jetables_perdus,
            "backpressure_events": self.backpressure_events,
        }


class BoundedEventQueue:
    """Queue bornée qui préfère CRIER plutôt que de perdre un fill en silence."""

    def __init__(self, *, max_size: int = 10_000) -> None:
        self.max_size = max(1, int(max_size))
        self._file: Deque[Event] = deque()
        self._vus: set[str] = set()                  # deduplication
        self._coalesce_index: dict[str, int] = {}    # cle -> position logique du dernier snapshot
        self._dernier_event_time_ms: int = -1
        self.metrics = QueueMetrics()
        self.backpressured = False

    # ------------------------------------------------------------------ ecriture

    def push(self, event: Event) -> str:
        """Rend le sort de l'evenement : ACCEPTED | DUPLICATE | COALESCED | DROPPED | BACKPRESSURE."""
        self.metrics.recus += 1

        if event.event_id and event.event_id in self._vus:
            self.metrics.doublons += 1
            return "DUPLICATE"                        # un snapshot rejoue n'est pas un fill neuf

        if event.event_time_ms < self._dernier_event_time_ms:
            self.metrics.hors_ordre += 1              # compte, mais on le garde : c'est une donnee
        self._dernier_event_time_ms = max(self._dernier_event_time_ms, event.event_time_ms)

        classe = classer(event.event_type)

        # --- coalescence : seul le DERNIER etat compte
        if classe == COALESCABLE and event.coalesce_key:
            for i, e in enumerate(self._file):
                if e.event_type == event.event_type and e.coalesce_key == event.coalesce_key:
                    self._file[i] = event             # le dernier ecrase l'ancien
                    self.metrics.coalesces += 1
                    if event.event_id:
                        self._vus.add(event.event_id)
                    return "COALESCED"

        # --- la file est pleine
        if len(self._file) >= self.max_size:
            if self._faire_de_la_place():
                pass                                  # on a jete un COALESCABLE / JETABLE
            elif classe == JAMAIS_JETABLE:
                # ON NE JETTE PAS UN FILL. On depasse la borne, et on CRIE.
                # Perdre ce signal serait pire que depasser la limite : on ne saurait meme pas
                # qu'on l'a perdu.
                self.backpressured = True
                self.metrics.backpressure_events += 1
                self._file.append(event)
                if event.event_id:
                    self._vus.add(event.event_id)
                return "BACKPRESSURE"
            else:
                self.metrics.jetes += 1
                return "DROPPED"                      # et c'est COMPTE, jamais silencieux

        self._file.append(event)
        if event.event_id:
            self._vus.add(event.event_id)
        return "ACCEPTED"

    def _faire_de_la_place(self) -> bool:
        """Jette le PREMIER evenement jetable trouve. **Jamais un JAMAIS_JETABLE.**"""
        for i, e in enumerate(self._file):
            if classer(e.event_type) != JAMAIS_JETABLE:
                del self._file[i]
                self.metrics.jetes += 1
                return True
        return False                                  # la file n'est faite QUE de fills : on ne jette rien

    # ------------------------------------------------------------------ lecture

    def pop(self) -> Event | None:
        """FIFO : le plus ANCIEN d'abord. C'est celui qu'on doit traiter -- pas celui qu'on jette."""
        if not self._file:
            return None
        e = self._file.popleft()
        self.metrics.traites += 1
        if len(self._file) < self.max_size:
            self.backpressured = False
        return e

    # ------------------------------------------------------------------ observabilite

    def depth(self) -> int:
        return len(self._file)

    def oldest_event_age_ms(self, now_ms: int) -> float | None:
        """L'age du plus vieil evenement EN ATTENTE. Un backlog qui gonfle invalide la fraicheur :
        un signal qui attend 30 s dans une file n'est plus un signal frais, quoi qu'en dise sa
        date d'origine."""
        if not self._file:
            return None
        return float(int(now_ms) - int(self._file[0].event_time_ms))

    def health(self, *, now_ms: int, max_lag_ms: float = 5_000.0) -> dict[str, Any]:
        age = self.oldest_event_age_ms(now_ms)
        return {
            "depth": self.depth(),
            "max_size": self.max_size,
            "oldest_event_age_ms": age,
            "backpressured": self.backpressured,
            "lag_depasse": bool(age is not None and age > max_lag_ms),
            # SI CE NOMBRE N'EST PAS ZERO, UN SIGNAL A ETE PERDU. Ce n'est pas une metrique
            # parmi d'autres : c'est la seule qui doit rester a zero.
            "jamais_jetables_perdus": self.metrics.jamais_jetables_perdus,
            "metrics": self.metrics.as_dict(),
        }


__all__ = [
    "COALESCABLE", "JAMAIS_JETABLE", "JETABLE",
    "TYPES_COALESCABLES", "TYPES_JAMAIS_JETABLES",
    "BoundedEventQueue", "Event", "QueueMetrics", "classer",
]
