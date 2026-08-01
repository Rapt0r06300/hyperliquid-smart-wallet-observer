"""[LANCEUR item 5] dYdX flux live — LE CHAÎNON MANQUANT.

Le défaut audité : `DydxIndexer.process_ws_message` existait mais N'ÉTAIT JAMAIS APPELÉ. Les observers WS
« live » gardaient tout en mémoire et ne touchaient jamais SQLite. Résultat : trades, positions,
subaccounts, carnets — jamais persistés depuis le temps réel.

Ce module RELIE le WS au stockage, sans réseau ni ordre :
  · on_message  → indexer.process_ws_message (persiste trades/positions/subaccounts/orderbooks, dédup) ;
  · on_gap      → indexer.gap_recovery via REST (rattrapage des fills manquants des subaccounts suivis) ;
  · heartbeat   → un battement par lot (item 7 pourra en lire la preuve de vie) ;
  · reprise     → au démarrage, backfill (markets + subaccounts + fills) depuis le dernier connu (cursor).

dYdX v4 LEGACY réel (indexer.dydx.trade) — RIEN à voir avec la simulation Hyperliquid : lecture seule,
0 ordre, 0 idée de la simu portée ici. Tout est injectable (indexer, messages, heartbeat, horloge) →
prouvé sans réseau.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence


@dataclass
class StatsFluxLive:
    messages: int = 0
    elements_persistes: int = 0
    gaps: int = 0
    fills_rattrapes: int = 0
    heartbeats: int = 0


def _attr(msg: Any, *noms: str, defaut: Any = None) -> Any:
    for n in noms:
        if isinstance(msg, dict) and n in msg:
            return msg[n]
        if hasattr(msg, n):
            return getattr(msg, n)
    return defaut


class PiloteFluxDydx:
    """Pilote de flux dYdX live : branche les callbacks WS sur la persistance, gère heartbeat + gap +
    reprise. `subaccounts` = liste (address, subaccount_number) suivis (pour la reprise et le rattrapage
    de trou). `heartbeat` : callable(nom, n_ecrites, dernier_exchange_ts) ; par défaut → heartbeat
    canonique sur `root` (import paresseux, jamais bloquant)."""

    def __init__(self, indexer: Any, *, network: str,
                 subaccounts: Sequence[tuple[str, int]] = (),
                 root: str | None = None, nom: str = "dydx-live",
                 heartbeat: Callable[[str, int, Any], None] | None = None) -> None:
        self.indexer = indexer
        self.network = network
        self.subaccounts = list(subaccounts)
        self.root = root
        self.nom = nom
        self._heartbeat = heartbeat
        self.stats = StatsFluxLive()

    # -- branchement WS -------------------------------------------------------------------------------
    def on_message(self, msg: Any) -> int:
        """Callback à passer à DydxIndexerWsClient(on_message=...). Persiste le message et bat le cœur."""
        channel = _attr(msg, "channel", defaut="")
        msg_type = _attr(msg, "type", "msg_type", defaut="")
        data = _attr(msg, "data", defaut={}) or {}
        n = int(self.indexer.process_ws_message(channel, msg_type, data, self.network))
        self.stats.messages += 1
        self.stats.elements_persistes += n
        self._battre(n, self._dernier_exchange_ts(data))
        return n

    def on_gap(self, channel: str, msg_id: Any = None) -> int:
        """Callback à passer à DydxIndexerWsClient(on_gap_detected=...). Rattrape via REST les fills
        manquants des subaccounts suivis (gap recovery)."""
        self.stats.gaps += 1
        rattrapes = 0
        for adresse, num in self.subaccounts:
            try:
                rattrapes += int(self.indexer.gap_recovery(adresse, num))
            except Exception:  # noqa: BLE001 — un rattrapage ne doit jamais tuer la boucle
                continue
        self.stats.fills_rattrapes += rattrapes
        return rattrapes

    def callbacks(self) -> tuple[Callable[[Any], int], Callable[[str, Any], int]]:
        """(on_message, on_gap) — exactement ce qu'attend DydxIndexerWsClient. LE branchement qui
        manquait entre le WS et la persistance."""
        return self.on_message, self.on_gap

    # -- reprise après crash --------------------------------------------------------------------------
    def reprendre(self) -> dict[str, int]:
        """Au (re)démarrage : backfill markets + chaque subaccount + ses fills, depuis le dernier connu.
        Idempotent grâce à la dédup du stockage (aucune donnée fabriquée, aucun doublon)."""
        marches = int(self.indexer.backfill_markets())
        subs = 0
        fills = 0
        for adresse, num in self.subaccounts:
            if self.indexer.backfill_subaccount(adresse, num):
                subs += 1
            fills += int(self.indexer.backfill_fills(adresse, num))
        return {"marches": marches, "subaccounts": subs, "fills": fills}

    # -- traitement d'un lot (replay / test) ----------------------------------------------------------
    def traiter_lot(self, messages: Iterable[Any]) -> int:
        total = 0
        for m in messages:
            total += self.on_message(m)
        return total

    # -- interne --------------------------------------------------------------------------------------
    @staticmethod
    def _dernier_exchange_ts(data: Any) -> Any:
        if not isinstance(data, dict):
            return None
        for cle in ("createdAt", "created_at_ms", "time", "ts"):
            if data.get(cle) is not None:
                return data[cle]
        trades = data.get("trades")
        if isinstance(trades, list) and trades and isinstance(trades[-1], dict):
            return trades[-1].get("createdAt")
        return None

    def _battre(self, n_ecrites: int, dernier_exchange_ts: Any) -> None:
        if self._heartbeat is not None:
            try:
                self._heartbeat(self.nom, n_ecrites, dernier_exchange_ts)
                self.stats.heartbeats += 1
            except Exception:  # noqa: BLE001
                pass
            return
        if not self.root:
            return
        try:
            from tools.heartbeat_collecteur import battre
            battre(self.root, self.nom, n_ecrites=n_ecrites, dernier_exchange_ts=dernier_exchange_ts,
                   note="dydx-live")
            self.stats.heartbeats += 1
        except Exception:  # noqa: BLE001 — heartbeat best-effort, jamais bloquant
            pass


__all__ = ["StatsFluxLive", "PiloteFluxDydx"]
