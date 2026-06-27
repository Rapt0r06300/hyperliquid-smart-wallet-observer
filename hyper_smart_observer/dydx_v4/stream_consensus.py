"""
Consensus temps réel à partir du firehose full node — READ-ONLY / PAPER.

Intégration DIRECTE (zéro REST) : chaque fill du flux est un signal directionnel
(wallet X achète/vend le marché M). On garde une fenêtre glissante des fills
récents et on détecte un CONSENSUS = K wallets distincts dans le même sens sur le
même marché, frais. Ça permet de traiter des milliers de fills/seconde sans
poller personne.

Le consensus produit un `ClusterSignal` (origin="stream") passé au même
`_evaluate_cluster` que le chemin REST → réutilise toutes les gates (edge,
liquidité, fraîcheur, risque). La gate "leaders prouvés" est sautée pour le
stream : sa qualité vient du nombre de wallets indépendants qui convergent.

Logique 100 % pure et testable. Aucune méthode d'ordre/signature.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional


def side_to_direction(side: str) -> str:
    """BUY → LONG (haussier), SELL → SHORT (baissier)."""
    return "LONG" if str(side).upper() == "BUY" else "SHORT"


@dataclass
class StreamFillWindow:
    """Fenêtre glissante des fills récents (ts, owner, clob_pair_id, direction)."""

    window_ms: int = 4000
    maxlen: int = 200_000
    _items: deque = field(default_factory=deque)

    def add(self, owner: str, market_key, direction: str, ts_ms: int) -> None:
        # market_key = ID node (int) OU nom de marché (str, ex "BTC-USD" via WS public).
        if not owner or market_key is None:
            return
        self._items.append((ts_ms, owner, market_key, direction))
        while len(self._items) > self.maxlen:
            self._items.popleft()

    def prune(self, now_ms: int) -> None:
        cutoff = now_ms - self.window_ms
        while self._items and self._items[0][0] < cutoff:
            self._items.popleft()

    def items(self) -> list:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)


@dataclass
class StreamSignal:
    clob_pair_id: int
    direction: str            # "LONG" | "SHORT"
    wallets: list[str]
    freshest_ts: int
    oldest_ts: int

    @property
    def wallet_count(self) -> int:
        return len(self.wallets)


def detect_consensus(items: list, min_wallets: int) -> list[StreamSignal]:
    """
    Détecter les consensus dans la fenêtre. `items` = [(ts, owner, clob, direction)].
    Groupe par (clob_pair_id, direction), garde ceux avec ≥ min_wallets distincts.
    """
    groups: dict[tuple, dict] = {}
    for ts, owner, clob, direction in items:
        g = groups.setdefault((clob, direction), {})
        prev = g.get(owner)
        g[owner] = ts if prev is None else max(prev, ts)
    out: list[StreamSignal] = []
    for (clob, direction), owners in groups.items():
        if len(owners) >= max(1, min_wallets):
            ts_values = list(owners.values())
            out.append(StreamSignal(
                clob_pair_id=clob, direction=direction,
                wallets=list(owners.keys()),
                freshest_ts=max(ts_values), oldest_ts=min(ts_values),
            ))
    # Plus de wallets d'abord (consensus le plus fort)
    out.sort(key=lambda s: s.wallet_count, reverse=True)
    return out


def build_cluster_signal(signal: StreamSignal, market: str, mark_price: float, now_ms: int):
    """Convertir un StreamSignal en ClusterSignal (origin='stream') pour le moteur."""
    from hyper_smart_observer.dydx_v4.cluster_detector import ClusterSignal
    age = max(0, now_ms - signal.freshest_ts)
    return ClusterSignal(
        market_id=market,
        side=signal.direction,
        wallet_count=signal.wallet_count,
        participating_wallets=list(signal.wallets),
        total_notional_usdc=0.0,
        first_wallet_opened_ms=signal.oldest_ts,
        last_wallet_opened_ms=signal.freshest_ts,
        signal_age_ms=age,
        avg_entry_price=float(mark_price or 0.0),
        signal_strength=min(1.0, signal.wallet_count / 5.0),
        market_priority=0.5,
        is_fresh=age < 4000,
        cluster_id=f"stream:{market}:{signal.direction}:{signal.freshest_ts}",
        origin="stream",
    )


__all__ = [
    "side_to_direction",
    "StreamFillWindow",
    "StreamSignal",
    "detect_consensus",
    "build_cluster_signal",
]
