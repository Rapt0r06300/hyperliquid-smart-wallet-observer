"""#286 (identité de session) + #312/#313/#384/#390 (moteur ÉVÉNEMENTIEL).

═══════════════════════════════════════════════════════════════════════════════════════════════
#286 — L'IDENTITÉ DE SESSION : **ne JAMAIS mélanger deux sessions**
═══════════════════════════════════════════════════════════════════════════════════════════════

Trois processus écrivent dans les mêmes fichiers : le collecteur, le moteur, le dashboard.
S'ils ne partagent pas la **même identité de session**, on obtient le pire des bugs de ce projet :

    ***Un PnL qui mélange deux runs, et personne qui se plaint.***

La règle projet est déjà écrite : *« ne jamais mélanger les PnL de test/replay avec le PnL live »*.
Mais **rien ne l'imposait**. Ici, chaque événement porte son `session_id` **et** son `mode`
(LIVE / BACKTEST / REPLAY / TEST_FIXTURE), et **le ledger REFUSE** un événement d'une autre
session ou d'un autre mode. *Un refus bruyant vaut mieux qu'une moyenne silencieuse.*

═══════════════════════════════════════════════════════════════════════════════════════════════
#312 / #313 / #384 / #390 — DÉCIDER À L'ARRIVÉE DU FILL, PAS EN FIN DE CYCLE
═══════════════════════════════════════════════════════════════════════════════════════════════

Aujourd'hui : une boucle qui scanne toutes les ~10 s (userFills 10 s, opportunity 10,6 s,
scan 10,3 s). **Un signal arrivé juste après le scan attend 10 secondes.**

⚠️ **HONNÊTETÉ — ce que ça N'APPORTE PAS.** La courbe edge/horizon est **PLATE** : passer de 10 s
à 10 ms **ne créera aucun edge**. *La latence n'a jamais été notre problème.*

    ***Alors pourquoi le faire ? Pour la VÉRITÉ, pas pour la vitesse.***

Une boucle à intervalle fixe **fabrique des artefacts** :
  * elle échantillonne le monde à un rythme qui n'a rien à voir avec l'arrivée de l'information ;
  * elle mélange des événements arrivés à 0,1 s et à 9,9 s **dans le même « instant » de décision** ;
  * elle rend **impossible** de rejouer exactement ce que le moteur a vu (#302).

**Un bus d'événements ordonné, horodaté et rejouable, c'est la condition d'un replay honnête.**
*Pas un gain de vitesse : un gain de VÉRITÉ.*

PUR : aucun réseau, aucun ordre réel.
"""
from __future__ import annotations

import hashlib
import heapq
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

LIVE = "LIVE"
BACKTEST = "BACKTEST"
REPLAY = "REPLAY"
TEST_FIXTURE = "TEST_FIXTURE"
MODES = (LIVE, BACKTEST, REPLAY, TEST_FIXTURE)

MOTIF_AUTRE_SESSION = "EVENEMENT_D_UNE_AUTRE_SESSION_REFUSE"
MOTIF_AUTRE_MODE = "EVENEMENT_D_UN_AUTRE_MODE_REFUSE_ON_NE_MELANGE_PAS_LES_PNL"
MOTIF_MODE_INCONNU = "MODE_INCONNU"


class SessionsMelangees(RuntimeError):
    """***Un PnL qui mélange deux runs est un PnL faux.*** On refuse **bruyamment**."""


@dataclass(frozen=True, slots=True)
class Session:
    """#286 — L'identité que les TROIS processus doivent partager."""
    session_id: str
    mode: str
    demarree_ms: int

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError("%s : %r (attendu %s)" % (MOTIF_MODE_INCONNU, self.mode,
                                                       ", ".join(MODES)))

    @property
    def live(self) -> bool:
        return self.mode == LIVE

    def as_dict(self) -> dict[str, Any]:
        return {"session_id": self.session_id, "mode": self.mode,
                "demarree_ms": self.demarree_ms, "real_execution": False}


def nouvelle_session(mode: str, *, graine: str | None = None,
                     maintenant_ms: int | None = None) -> Session:
    """L'ID est **déterministe** en test (graine) et unique en live."""
    t = int(time.time() * 1000) if maintenant_ms is None else int(maintenant_ms)
    base = graine if graine is not None else "%s-%d-%d" % (mode, t, id(object()))
    sid = hashlib.sha256(base.encode()).hexdigest()[:12]
    return Session(session_id=sid, mode=mode, demarree_ms=t)


@dataclass(frozen=True, slots=True)
class Evenement:
    """Chaque événement porte **son horloge, sa session et son mode**. Sans exception."""
    t_ms: int                  # 🔴 horloge LOCALE de réception, jamais dérivée des données
    type: str
    charge: Any
    session_id: str
    mode: str
    seq: int = 0               # départage deux événements à la même milliseconde

    def as_dict(self) -> dict[str, Any]:
        return {"t_ms": self.t_ms, "type": self.type, "session_id": self.session_id,
                "mode": self.mode, "seq": self.seq, "real_execution": False}


class BusEvenements:
    """#312/#313/#384/#390 — **Un ordre TOTAL, déterministe, rejouable.**

    *Deux exécutions sur les mêmes événements doivent donner exactement le même résultat.*
    Sans ça, le replay (#302) et le shadow mode ne valent rien.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self._tas: list[tuple[int, int, Evenement]] = []
        self._seq = 0
        self._handlers: dict[str, list[Callable[[Evenement], None]]] = {}
        self.refuses_autre_session = 0
        self.refuses_autre_mode = 0

    # --- #286 : LE GARDE ---------------------------------------------------------------------
    def publier(self, t_ms: int, type_: str, charge: Any,
                *, session_id: str | None = None, mode: str | None = None) -> Evenement:
        sid = self.session.session_id if session_id is None else session_id
        m = self.session.mode if mode is None else mode

        if sid != self.session.session_id:
            self.refuses_autre_session += 1
            raise SessionsMelangees(
                "%s : %s != %s. **Un PnL qui melange deux runs est un PnL FAUX.**"
                % (MOTIF_AUTRE_SESSION, sid, self.session.session_id))
        if m != self.session.mode:
            self.refuses_autre_mode += 1
            raise SessionsMelangees(
                "%s : %s != %s. *La regle du projet l'interdisait deja -- **rien ne l'imposait.***"
                % (MOTIF_AUTRE_MODE, m, self.session.mode))

        self._seq += 1
        e = Evenement(t_ms=int(t_ms), type=type_, charge=charge,
                      session_id=sid, mode=m, seq=self._seq)
        heapq.heappush(self._tas, (e.t_ms, e.seq, e))
        return e

    def souscrire(self, type_: str, handler: Callable[[Evenement], None]) -> None:
        self._handlers.setdefault(type_, []).append(handler)

    def drainer(self) -> Iterator[Evenement]:
        """Rend les événements **par ordre chronologique STRICT**, `seq` départageant les ex æquo.

        ***C'est ça, « décider à l'arrivée du fill » : l'ordre est celui du MONDE, pas celui d'une
        boucle de 10 secondes.***
        """
        while self._tas:
            _, _, e = heapq.heappop(self._tas)
            for h in self._handlers.get(e.type, []):
                h(e)
            yield e

    def __len__(self) -> int:
        return len(self._tas)


def empreinte_du_flux(evenements: list[Evenement]) -> str:
    """🔑 **La preuve du déterminisme.** Deux exécutions identiques -> même empreinte.

    Si elle change alors que les entrées n'ont pas changé, **le moteur n'est pas rejouable** —
    et le replay (#302) comme le shadow mode ne valent rien.
    """
    h = hashlib.sha256()
    for e in evenements:
        h.update(("%d|%d|%s|%s|%s" % (e.t_ms, e.seq, e.type, e.session_id, e.mode)).encode())
    return h.hexdigest()[:16]


__all__ = [
    "BACKTEST", "LIVE", "MODES", "MOTIF_AUTRE_MODE", "MOTIF_AUTRE_SESSION",
    "MOTIF_MODE_INCONNU", "REPLAY", "TEST_FIXTURE",
    "BusEvenements", "Evenement", "Session", "SessionsMelangees",
    "empreinte_du_flux", "nouvelle_session",
]
