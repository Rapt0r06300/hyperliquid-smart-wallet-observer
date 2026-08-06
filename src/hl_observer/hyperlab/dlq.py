"""[Bloc 33 / AUD-386] Dead Letter Queue : messages inconnus ou non-parsables mis en QUARANTAINE
(jamais silencieusement droppes, jamais devines). Chaque entree garde la raison + la source + le brut.
stdlib pure, deterministe."""
from __future__ import annotations

from typing import Optional


class DeadLetterQueue:
    def __init__(self) -> None:
        self._items = []

    def quarantaine(self, brut, *, source: str, raison: str, ts: Optional[float] = None) -> dict:
        e = {"source": source, "raison": raison, "ts": ts, "brut": brut}
        self._items.append(e)
        return e

    def parse_ou_dlq(self, brut, parser, *, source: str, ts: Optional[float] = None):
        """Tente parser(brut). En cas d'echec (exception) OU de None -> DLQ (jamais un faux resultat)."""
        try:
            out = parser(brut)
        except Exception as exc:  # parsing hostile : on quarantaine, on ne devine pas
            self.quarantaine(brut, source=source, raison="exception:%s" % type(exc).__name__, ts=ts)
            return None
        if out is None:
            self.quarantaine(brut, source=source, raison="parse_none", ts=ts)
        return out

    def __len__(self):
        return len(self._items)

    def items(self):
        return list(self._items)

    def par_source(self) -> dict:
        out: dict = {}
        for e in self._items:
            out[e["source"]] = out.get(e["source"], 0) + 1
        return out
