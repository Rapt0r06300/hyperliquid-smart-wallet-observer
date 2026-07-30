"""P3.2b (§5.2) — orchestration du carnet Binance : snapshot REST + BUFFER des diffs WS + resync auto.

Le carnet `BinanceDepthBook` sait appliquer un snapshot et des diffs contigus. Il manque la LOGIQUE
d'orchestration réelle : bufferiser les diffs WS arrivés AVANT le snapshot REST, les rejouer une fois
le snapshot posé, et — sur toute rupture — déclencher un RE-SNAPSHOT automatique en rebufferisant.
Ce module fournit cela, avec publication CANONIQUE (exchange_ts / receive_ts / sequence / quality).

Règle dure : un carnet DESYNC n'est **jamais** publié comme exploitable — `quality=DESYNC` et
`needs_resnapshot=True`. La récupération n'est pas devinée : elle passe par un nouveau snapshot.
Le fetch WS/REST réel est branché ailleurs (collecteur) ; ici tout est pur et testable hors ligne.
"""
from __future__ import annotations

from typing import Any, Iterable

from hl_observer.collection.binance_depth_book import APPLIQUE, BinanceDepthBook

SCHEMA_VERSION = "hypersmart.binance_depth_orchestrator.v1"

BUFFERISE = "BUFFERISE"


class BinanceDepthOrchestrator:
    """Gère snapshot + buffer de diffs + resync automatique pour UN symbole Binance."""

    def __init__(self, *, futures: bool = False, max_buffer: int = 5_000) -> None:
        self.book = BinanceDepthBook(futures=futures)
        self.buffer: list[dict[str, Any]] = []
        self.needs_snapshot = True
        self.max_buffer = int(max_buffer)
        self.exchange_ts_ms: int | None = None
        self.receive_ts_ms: int | None = None
        self.resync_count = 0

    def _maj_ts(self, exchange_ts_ms, receive_ts_ms) -> None:
        if exchange_ts_ms is not None:
            self.exchange_ts_ms = int(exchange_ts_ms)
        if receive_ts_ms is not None:
            self.receive_ts_ms = int(receive_ts_ms)

    def sur_diff(self, *, U: int, u: int, pu: int | None = None,
                 bids: Iterable[Any] = (), asks: Iterable[Any] = (),
                 exchange_ts_ms: int | None = None, receive_ts_ms: int | None = None) -> str:
        """Reçoit un diff WS. Buffer si pas encore de snapshot ; sinon applique ; DESYNC → resync auto."""
        self._maj_ts(exchange_ts_ms, receive_ts_ms)
        d = {"U": int(U), "u": int(u), "pu": pu, "bids": list(bids), "asks": list(asks)}

        if self.needs_snapshot or self.book.last_update_id is None:
            self.buffer.append(d)
            if len(self.buffer) > self.max_buffer:
                self.buffer.pop(0)                      # borne le buffer (garde les plus récents)
            return BUFFERISE

        res = self.book.appliquer_diff(U=d["U"], u=d["u"], pu=d["pu"], bids=d["bids"], asks=d["asks"])
        if res.status.startswith("DESYNC"):
            self.needs_snapshot = True                  # resync automatique : redemander un snapshot
            self.buffer = [d]                           # et rebufferiser à partir de ce diff
        return res.status

    def sur_snapshot(self, *, last_update_id: int, bids: Iterable[Any] = (), asks: Iterable[Any] = (),
                     exchange_ts_ms: int | None = None, receive_ts_ms: int | None = None) -> dict[str, Any]:
        """Pose le snapshot REST et rejoue le buffer. Si le buffer ne raccorde pas → nouveau snapshot requis."""
        self._maj_ts(exchange_ts_ms, receive_ts_ms)
        self.book.appliquer_snapshot(last_update_id=last_update_id, bids=bids, asks=asks)
        self.needs_snapshot = False
        self.resync_count += 1

        en_attente = self.buffer
        self.buffer = []
        applied = 0
        for d in en_attente:
            r = self.book.appliquer_diff(U=d["U"], u=d["u"], pu=d["pu"], bids=d["bids"], asks=d["asks"])
            if r.status == APPLIQUE:
                applied += 1
            elif r.status.startswith("DESYNC"):
                self.needs_snapshot = True              # le buffer ne raccorde pas → re-snapshot
                break
        return {"applied_from_buffer": applied, "needs_snapshot": self.needs_snapshot}

    def besoin_resnapshot(self) -> bool:
        return self.needs_snapshot or not self.book.exploitable()

    def publier(self, depth: int = 10) -> dict[str, Any]:
        """Publication CANONIQUE : carnet + timestamps + sequence + quality. DESYNC ⇒ non exploitable."""
        snap = self.book.snapshot(depth)
        snap.update({
            "schema_version": SCHEMA_VERSION,
            "exchange_ts_ms": self.exchange_ts_ms,
            "receive_ts_ms": self.receive_ts_ms,
            "sequence": self.book.last_update_id,
            "quality": "EXPLOITABLE" if self.book.exploitable() else "DESYNC",
            "needs_resnapshot": self.besoin_resnapshot(),
            "resync_count": self.resync_count,
        })
        return snap


__all__ = ["SCHEMA_VERSION", "BUFFERISE", "BinanceDepthOrchestrator"]
