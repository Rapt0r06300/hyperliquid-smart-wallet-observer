"""P3.2 (§5.2) — carnet de PROFONDEUR Binance multi-niveaux : snapshot + deltas resynchronisés.

Le collecteur actuel a bookTicker + trades mais **pas** de vraie profondeur Binance. Ce module
maintient un carnet L2 local à partir d'un snapshot REST (`lastUpdateId`) et du flux de diffs
(`U` = premier update id, `u` = dernier ; `pu` = update id précédent, en futures), en suivant
L'ALGORITHME OFFICIEL Binance :

  1. snapshot initialise le carnet et `lastUpdateId` ;
  2. un diff dont `u <= lastUpdateId` est ANTÉRIEUR → ignoré ;
  3. le PREMIER diff appliqué doit encadrer `lastUpdateId+1` (`U <= lastUpdateId+1 <= u`) ;
  4. ensuite chaque diff doit être CONTIGU (`U == u_précédent + 1`, ou `pu == u_précédent` en futures) ;
  5. une quantité 0 supprime le niveau.

Toute rupture de contiguïté = **DESYNC** : deny-by-default, le carnet refuse d'appliquer et redevient
inexploitable tant qu'un nouveau snapshot ne l'a pas ré-ancré. On ne devine JAMAIS un carnet troué.
Pur, 0 réseau (le fetch WS/REST live est branché ailleurs) — donc entièrement testable hors ligne.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

SCHEMA_VERSION = "hypersmart.binance_depth_book.v1"

SNAPSHOT_REQUIS = "SNAPSHOT_REQUIS"
IGNORE_ANTERIEUR = "IGNORE_ANTERIEUR"
APPLIQUE = "APPLIQUE"
DESYNC_PREMIER = "DESYNC_PREMIER"
DESYNC_GAP = "DESYNC_GAP"
DESYNC = "DESYNC"


def _num(x: object) -> float | None:
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


@dataclass(frozen=True, slots=True)
class ResultatDiff:
    status: str
    detail: str | None = None
    last_update_id: int | None = None


def _paires(niveaux: Iterable[Any]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for n in niveaux or ():
        try:
            p, q = float(n[0]), float(n[1])
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(p) and math.isfinite(q) and p > 0 and q >= 0:
            out.append((p, q))
    return out


class BinanceDepthBook:
    """Carnet L2 Binance maintenu par snapshot + diffs, avec détection de DESYNC (deny-by-default)."""

    def __init__(self, *, futures: bool = False) -> None:
        self.futures = bool(futures)
        self.last_update_id: int | None = None
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.desync: str | None = None
        self._diff_applique = False

    # ---- ancrage ----
    def appliquer_snapshot(self, *, last_update_id: int, bids: Iterable[Any] = (), asks: Iterable[Any] = ()) -> None:
        self.last_update_id = int(last_update_id)
        self.bids = {p: q for p, q in _paires(bids) if q > 0}
        self.asks = {p: q for p, q in _paires(asks) if q > 0}
        self.desync = None
        self._diff_applique = False

    # ---- flux de diffs ----
    def appliquer_diff(self, *, U: int, u: int, pu: int | None = None,
                       bids: Iterable[Any] = (), asks: Iterable[Any] = ()) -> ResultatDiff:
        if self.last_update_id is None:
            return ResultatDiff(SNAPSHOT_REQUIS)
        if self.desync:
            return ResultatDiff(DESYNC, detail=self.desync, last_update_id=self.last_update_id)
        U, u = int(U), int(u)

        if u <= self.last_update_id:
            return ResultatDiff(IGNORE_ANTERIEUR, last_update_id=self.last_update_id)

        if not self._diff_applique:
            if not (U <= self.last_update_id + 1 <= u):
                self.desync = f"PREMIER_HORS_BORNE U={U} u={u} snapshot={self.last_update_id}"
                return ResultatDiff(DESYNC_PREMIER, detail=self.desync, last_update_id=self.last_update_id)
        else:
            attendu = self.last_update_id + 1
            if self.futures and pu is not None:
                if int(pu) != self.last_update_id:
                    self.desync = f"PU_DISCONTINU pu={pu} u_precedent={self.last_update_id}"
                    return ResultatDiff(DESYNC_GAP, detail=self.desync, last_update_id=self.last_update_id)
            elif U != attendu:
                self.desync = f"GAP U={U} attendu={attendu}"
                return ResultatDiff(DESYNC_GAP, detail=self.desync, last_update_id=self.last_update_id)

        self._appliquer(self.bids, bids)
        self._appliquer(self.asks, asks)
        self.last_update_id = u
        self._diff_applique = True
        return ResultatDiff(APPLIQUE, last_update_id=self.last_update_id)

    @staticmethod
    def _appliquer(cote: dict[float, float], updates: Iterable[Any]) -> None:
        for p, q in _paires(updates):
            if q == 0:
                cote.pop(p, None)      # quantité 0 = niveau retiré
            else:
                cote[p] = q

    # ---- lecture ----
    def best_bid(self) -> float | None:
        return max(self.bids) if (self.bids and not self.desync) else None

    def best_ask(self) -> float | None:
        return min(self.asks) if (self.asks and not self.desync) else None

    def mid(self) -> float | None:
        bb, ba = self.best_bid(), self.best_ask()
        return round((bb + ba) / 2.0, 12) if (bb is not None and ba is not None) else None

    def exploitable(self) -> bool:
        """Un carnet DESYNC n'est pas exploitable : deny-by-default (UNMEASURABLE, pas faux)."""
        return self.last_update_id is not None and self.desync is None

    def snapshot(self, depth: int = 10) -> dict[str, Any]:
        bids = sorted(self.bids.items(), key=lambda kv: kv[0], reverse=True)[:depth]
        asks = sorted(self.asks.items(), key=lambda kv: kv[0])[:depth]
        return {
            "schema_version": SCHEMA_VERSION,
            "exploitable": self.exploitable(),
            "desync": self.desync,
            "last_update_id": self.last_update_id,
            "bids": [[p, q] for p, q in bids],
            "asks": [[p, q] for p, q in asks],
            "best_bid": self.best_bid(), "best_ask": self.best_ask(), "mid": self.mid(),
            "real_execution": False,
        }


__all__ = [
    "SCHEMA_VERSION", "SNAPSHOT_REQUIS", "IGNORE_ANTERIEUR", "APPLIQUE",
    "DESYNC_PREMIER", "DESYNC_GAP", "DESYNC", "ResultatDiff", "BinanceDepthBook",
]
