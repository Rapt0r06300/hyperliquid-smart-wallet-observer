"""IMPROVE-05 (#112) — le journal de latence, et le BIAIS DE SURVIVANT qu'il corrige.

CE QU'ON A TROUVÉ (2026-07-13)
------------------------------
`LatencyTrace` était bien créée et estampillée sur le chemin vivant
(`fusion_paper_engine_adapter`). Mais son `as_dict()` n'était écrit que dans le
`decision_context` d'une décision **qui aboutit**. Les chemins de REFUS
(`CONSENSUS_TOO_WEAK`, `STALE_SIGNAL`, `decision != FOLLOW`) sortent **avant** tout tampon.

    >>> On ne mesurait la latence QUE des trades qu'on PREND. <<<

C'est un **biais de survivant dans l'instrumentation elle-même**. Or les refus sont l'immense
majorité des passages — et ce sont précisément eux qu'on veut comprendre : *« a-t-on refusé ce
signal parce qu'il était mauvais, ou parce qu'on est arrivé trop tard ? »* Sans latence sur les
refus, cette question n'a **aucune** réponse possible.

Et `resumer()` (p50/p95) n'était appelée par personne : on enregistrait des traces une par une,
sans jamais pouvoir répondre à *« quelle est notre latence ? »*.

CE QUE FAIT CE MODULE
---------------------
Un journal **borné**, en mémoire, qui accepte **toutes** les traces — acceptées ET refusées —
et sait les résumer. Borné, parce qu'un run de 48 h ne doit pas mourir de son propre journal
(le bloat de DB a DÉJÀ fait crasher un run, le 08/07).

⚠️ Ce module MESURE. Il ne décide de rien, il n'ouvre rien, il ne refuse rien.
Rappel de la zone morte Z1 : **la courbe edge/horizon est PLATE** — optimiser la latence
n'améliorera pas le PnL. On mesure pour *savoir*, pas pour *espérer*.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

from hl_observer.runtime.latency_trace import LatencyTrace, resumer

#: Un run de 48 h ne doit jamais mourir de son propre journal.
CAPACITE_DEFAUT = 5_000

ISSUE_ACCEPTE = "ACCEPTE"
ISSUE_REFUSE = "REFUSE"


@dataclass(frozen=True, slots=True)
class Entree:
    """Une trace + CE QU'ELLE EST DEVENUE. Le lien entre les deux est tout l'intérêt."""

    trace: LatencyTrace
    issue: str            # ACCEPTE | REFUSE
    motif: str = ""       # le motif du refus, s'il y en a un


class JournalLatence:
    """Borné, thread-safe, et il n'oublie PAS les refus."""

    def __init__(self, capacite: int = CAPACITE_DEFAUT) -> None:
        self._entrees: deque[Entree] = deque(maxlen=max(1, int(capacite)))
        self._verrou = threading.Lock()

    def enregistrer(self, trace: LatencyTrace, issue: str, motif: str = "") -> None:
        if issue not in (ISSUE_ACCEPTE, ISSUE_REFUSE):
            raise ValueError(
                "issue doit etre ACCEPTE ou REFUSE, pas %r. Une trace sans issue ne sert a rien : "
                "c'est justement le LIEN entre la latence et le sort du signal qui nous interesse."
                % (issue,)
            )
        with self._verrou:
            self._entrees.append(Entree(trace=trace, issue=issue, motif=str(motif or "")))

    def __len__(self) -> int:
        with self._verrou:
            return len(self._entrees)

    def _copie(self) -> list[Entree]:
        with self._verrou:
            return list(self._entrees)

    def resume(self) -> dict[str, Any]:
        """p50/p95 GLOBAL, et surtout **séparé accepté / refusé**.

        Si les refus sont systématiquement plus LENTS que les acceptations, ce n'est pas le
        hasard : c'est qu'on arrive trop tard, et qu'on refuse *ensuite*. Cette comparaison est
        impossible tant que les refus ne sont pas mesurés — c'était le cas jusqu'ici.
        """
        entrees = self._copie()
        acceptes = [e.trace for e in entrees if e.issue == ISSUE_ACCEPTE]
        refuses = [e.trace for e in entrees if e.issue == ISSUE_REFUSE]

        motifs: dict[str, int] = {}
        for e in entrees:
            if e.issue == ISSUE_REFUSE and e.motif:
                motifs[e.motif] = motifs.get(e.motif, 0) + 1

        return {
            "n": len(entrees),
            "n_acceptes": len(acceptes),
            "n_refuses": len(refuses),
            "global": resumer(e.trace for e in entrees),
            "acceptes": resumer(acceptes),
            "refuses": resumer(refuses),
            "motifs_de_refus": dict(sorted(motifs.items(), key=lambda kv: -kv[1])),
            "borne": self._entrees.maxlen,
        }


#: Journal du process. Le runtime y écrit ; le dashboard le lit. Personne n'y décide quoi que ce soit.
JOURNAL = JournalLatence()


def enregistrer(trace: LatencyTrace, issue: str, motif: str = "") -> None:
    """Point d'entrée unique. `try/except` chez l'appelant : un journal cassé ne doit RIEN bloquer."""
    JOURNAL.enregistrer(trace, issue, motif)


def resume() -> dict[str, Any]:
    return JOURNAL.resume()


__all__ = [
    "CAPACITE_DEFAUT",
    "ISSUE_ACCEPTE",
    "ISSUE_REFUSE",
    "Entree",
    "JournalLatence",
    "JOURNAL",
    "enregistrer",
    "resume",
]
