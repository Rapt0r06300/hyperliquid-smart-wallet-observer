"""
Détecteur de clusters de wallets dYdX v4.

Basé sur l'analyse empirique (1.48M events Hyperliquid):
- ETH: winrate 41% à 1 wallet, signal age 3s = meilleur coin
- Consensus 2+ wallets sur même marché/direction dans 60s = signal valide
- Stop-loss OBLIGATOIRE: sans stop, HYPE SHORT a perdu -$20

PAPER-ONLY. Aucun ordre réel.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from hyper_smart_observer.dydx_v4.models import PositionSide

logger = logging.getLogger(__name__)

# Fenêtre de consensus: si K wallets ouvrent dans cette fenêtre → cluster signal
CONSENSUS_WINDOW_MS = 60_000  # 60 secondes

# Marchés prioritaires prouvés (ETH en premier d'après l'analyse)
PRIORITY_MARKETS_ORDERED = [
    "ETH-USD", "BTC-USD", "SOL-USD", "TIA-USD",
    "AVAX-USD", "BNB-USD", "ARB-USD", "OP-USD",
]

# Marchés bloqués (jamais de signal)
BLOCKED_MARKETS = frozenset([
    "CASH:WTI", "CASH:TSLA", "CASH:SILVER", "CASH:GOLD",
    "XYZ:CL", "HYPE", "ZEC",
])


@dataclass
class WalletPosition:
    """Position ouverte d'un wallet suivi."""
    address: str
    market_id: str
    side: str  # "LONG" ou "SHORT"
    size: float
    entry_price: float
    opened_at_ms: int
    last_seen_ms: int
    fill_id: Optional[str] = None
    notional_usdc: float = 0.0


@dataclass
class ClusterSignal:
    """
    Signal de cluster: K wallets dans la même direction sur le même marché.

    PAPER-ONLY. Ce signal ne déclenche aucun ordre réel.
    """
    market_id: str
    side: str           # "LONG" ou "SHORT"
    wallet_count: int
    participating_wallets: list[str]
    total_notional_usdc: float
    first_wallet_opened_ms: int
    last_wallet_opened_ms: int
    signal_age_ms: int  # âge du premier signal
    avg_entry_price: float
    signal_strength: float  # 0.0 → 1.0 (composite)
    market_priority: float  # 0.0 → 1.0 (ETH=1.0)
    is_fresh: bool          # True si signal_age_ms < 4000
    cluster_id: str
    detected_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    # Origine: "rest" (poll positions) ou "stream" (full node firehose temps réel).
    # Les clusters "stream" sautent la gate proven (qualité = consensus K wallets).
    origin: str = "rest"
    flow_trade_count: Optional[int] = None
    flow_large_trade_usdc: Optional[float] = None

    @property
    def is_actionable(self) -> bool:
        """
        Signal actif si:
        - 2+ wallets
        - Marché non bloqué
        - Signal frais (<60s depuis le premier wallet)
        - Marché prioritaire
        """
        return (
            self.wallet_count >= 2
            and self.market_id not in BLOCKED_MARKETS
            and self.signal_age_ms < CONSENSUS_WINDOW_MS
            and self.market_priority > 0
        )


@dataclass
class PositionEvent:
    """Événement détecté sur la position d'un wallet."""
    event_type: str  # "OPEN", "ADD", "REDUCE", "CLOSE"
    address: str
    market_id: str
    side: str
    price: float
    size: float
    notional_usdc: float
    fill_id: Optional[str]
    detected_at_ms: int
    signal_age_ms: int = 0


class DydxClusterDetector:
    """
    Détecte en temps réel quand plusieurs wallets convergent sur le même trade.

    Logique:
    - Maintient un snapshot des positions de chaque wallet suivi
    - Détecte les nouvelles ouvertures (OPEN events)
    - Groupe par (market, side) dans la fenêtre de 60s
    - Retourne un ClusterSignal quand K>=2 wallets s'alignent

    PAPER-ONLY. Aucun appel d'API privée.
    """

    def __init__(
        self,
        consensus_window_ms: int = CONSENSUS_WINDOW_MS,
        min_wallets_for_signal: int = 2,
        min_notional_usdc: float = 10_000.0,
    ) -> None:
        self.consensus_window_ms = consensus_window_ms
        self.min_wallets = min_wallets_for_signal
        self.min_notional = min_notional_usdc

        # État: positions actuelles par wallet
        self._positions: dict[str, dict[str, WalletPosition]] = {}
        # État précédent pour détecter les changements
        self._prev_positions: dict[str, dict[str, WalletPosition]] = {}
        # Fenêtre d'ouvertures récentes: (market, side) → list[(wallet, opened_ms, price, notional)]
        self._recent_opens: dict[tuple, list] = {}

    def update_positions(
        self,
        address: str,
        positions_raw: list[dict],
        fetched_at_ms: Optional[int] = None,
    ) -> list[PositionEvent]:
        """
        Mettre à jour les positions d'un wallet et détecter les changements.

        Args:
            address: adresse dYdX (dydx1...)
            positions_raw: liste de positions normalisées depuis l'Indexer
            fetched_at_ms: timestamp de récupération (pour calcul signal age)

        Returns:
            Liste d'événements détectés (OPEN, CLOSE, ADD, REDUCE)
        """
        now_ms = fetched_at_ms or int(time.time() * 1000)
        events: list[PositionEvent] = []

        # Parser les nouvelles positions
        new_positions: dict[str, WalletPosition] = {}
        for pos in positions_raw:
            market = pos.get("market") or pos.get("market_id", "")
            side = pos.get("side", "")
            if not market or not side:
                continue
            if market in BLOCKED_MARKETS:
                continue

            try:
                size = float(pos.get("size", 0))
                entry_price = float(pos.get("entryPrice") or pos.get("entry_price", 0))
            except (ValueError, TypeError):
                continue

            if size <= 0:
                continue

            notional = size * entry_price
            key = f"{market}:{side}"
            new_positions[key] = WalletPosition(
                address=address,
                market_id=market,
                side=side,
                size=size,
                entry_price=entry_price,
                opened_at_ms=now_ms,
                last_seen_ms=now_ms,
                notional_usdc=notional,
            )

        prev = self._positions.get(address, {})

        # Détecter OPEN (nouvelle position absente avant)
        for key, pos in new_positions.items():
            if key not in prev:
                event = PositionEvent(
                    event_type="OPEN",
                    address=address,
                    market_id=pos.market_id,
                    side=pos.side,
                    price=pos.entry_price,
                    size=pos.size,
                    notional_usdc=pos.notional_usdc,
                    fill_id=None,
                    detected_at_ms=now_ms,
                )
                events.append(event)
                logger.info("OPEN detected: %s %s %s size=%.4f", address[:12], pos.market_id, pos.side, pos.size)

                # Enregistrer dans la fenêtre de consensus
                cluster_key = (pos.market_id, pos.side)
                if cluster_key not in self._recent_opens:
                    self._recent_opens[cluster_key] = []
                self._recent_opens[cluster_key].append((address, now_ms, pos.entry_price, pos.notional_usdc))

            else:
                # Position existante: détecter ADD ou REDUCE
                prev_pos = prev[key]
                delta = pos.size - prev_pos.size
                if abs(delta) > 1e-8:
                    etype = "ADD" if delta > 0 else "REDUCE"
                    events.append(PositionEvent(
                        event_type=etype,
                        address=address,
                        market_id=pos.market_id,
                        side=pos.side,
                        price=pos.entry_price,
                        size=abs(delta),
                        notional_usdc=abs(delta) * pos.entry_price,
                        fill_id=None,
                        detected_at_ms=now_ms,
                    ))

        # Détecter CLOSE (position présente avant, absente maintenant)
        for key, prev_pos in prev.items():
            if key not in new_positions:
                events.append(PositionEvent(
                    event_type="CLOSE",
                    address=address,
                    market_id=prev_pos.market_id,
                    side=prev_pos.side,
                    price=prev_pos.entry_price,
                    size=prev_pos.size,
                    notional_usdc=prev_pos.notional_usdc,
                    fill_id=None,
                    detected_at_ms=now_ms,
                ))
                logger.info("CLOSE detected: %s %s %s", address[:12], prev_pos.market_id, prev_pos.side)

        # Mise à jour état
        self._prev_positions[address] = prev
        self._positions[address] = new_positions

        return events

    def update_from_fill(
        self,
        address: str,
        market_id: str,
        side: str,  # "BUY" ou "SELL"
        size: float,
        price: float,
        fill_id: Optional[str] = None,
        fill_ts_ms: Optional[int] = None,
    ) -> Optional[PositionEvent]:
        """
        Mettre à jour depuis un fill WebSocket (temps réel, signal age proche de 0).

        Args:
            side: "BUY" ou "SELL" (fill side, pas position side)
        """
        now_ms = fill_ts_ms or int(time.time() * 1000)
        signal_age = int(time.time() * 1000) - now_ms

        # BUY fill → ouverture LONG ou fermeture SHORT
        # SELL fill → ouverture SHORT ou fermeture LONG
        position_side = "LONG" if side == "BUY" else "SHORT"
        notional = size * price

        pos_key = f"{market_id}:{position_side}"
        existing = self._positions.get(address, {}).get(pos_key)

        event_type = "OPEN" if not existing else "ADD"
        if existing:
            # Vérifier si c'est un close (direction opposée)
            is_close = (
                (existing.side == "LONG" and side == "SELL") or
                (existing.side == "SHORT" and side == "BUY")
            )
            if is_close:
                event_type = "CLOSE"
                position_side = existing.side

        if event_type == "OPEN":
            if market_id not in BLOCKED_MARKETS:
                cluster_key = (market_id, position_side)
                if cluster_key not in self._recent_opens:
                    self._recent_opens[cluster_key] = []
                self._recent_opens[cluster_key].append((address, now_ms, price, notional))
                logger.info(
                    "FILL→OPEN: %s %s %s price=%.4f size=%.4f age=%dms",
                    address[:12], market_id, position_side, price, size, signal_age
                )

        return PositionEvent(
            event_type=event_type,
            address=address,
            market_id=market_id,
            side=position_side,
            price=price,
            size=size,
            notional_usdc=notional,
            fill_id=fill_id,
            detected_at_ms=now_ms,
            signal_age_ms=signal_age,
        )

    def reset_wallet(self, address: str) -> None:
        """Réinitialiser l'état d'un wallet dans le cluster detector.

        Efface la snapshot précédente: le prochain update_positions() traitera
        toutes les positions comme NEW → événements OPEN frais générés.
        Utilisé par le mode DEMO pour forcer un cycle OPEN/CLOSE périodique.
        PAPER SIMULATION ONLY.
        """
        self._positions.pop(address, None)
        self._prev_positions.pop(address, None)

    def detect_clusters(
        self,
        min_wallets: Optional[int] = None,
    ) -> list[ClusterSignal]:
        """
        Détecter les clusters actifs (K+ wallets même direction).

        Nettoie les entrées trop vieilles (> consensus_window_ms).
        Retourne les clusters triés par signal_strength DESC.
        """
        now_ms = int(time.time() * 1000)
        min_w = min_wallets or self.min_wallets

        # Nettoyer les vieux opens
        cutoff = now_ms - self.consensus_window_ms
        for key in list(self._recent_opens.keys()):
            self._recent_opens[key] = [
                entry for entry in self._recent_opens[key]
                if entry[1] >= cutoff  # entry[1] = opened_ms
            ]
            if not self._recent_opens[key]:
                del self._recent_opens[key]

        clusters: list[ClusterSignal] = []

        for (market_id, side), entries in self._recent_opens.items():
            if market_id in BLOCKED_MARKETS:
                continue
            if len(entries) < min_w:
                continue

            # Dédupliquer par wallet (garder le dernier)
            wallets_seen: dict[str, tuple] = {}
            for addr, opened_ms, price, notional in entries:
                wallets_seen[addr] = (opened_ms, price, notional)

            if len(wallets_seen) < min_w:
                continue

            # Construire le cluster
            first_ms = min(v[0] for v in wallets_seen.values())
            last_ms = max(v[0] for v in wallets_seen.values())
            total_notional = sum(v[2] for v in wallets_seen.values())
            avg_price = (
                sum(v[1] * v[2] for v in wallets_seen.values()) /
                max(total_notional, 1e-10)
            )
            signal_age = now_ms - first_ms

            if total_notional < self.min_notional:
                continue

            # Market priority
            market_prio = {
                "ETH-USD": 1.0, "BTC-USD": 0.9, "SOL-USD": 0.7,
                "TIA-USD": 0.6, "AVAX-USD": 0.5, "BNB-USD": 0.5,
            }.get(market_id, 0.3)

            # Signal strength: wallet count + notional + freshness + priority
            import math
            freshness = max(0.0, 1.0 - signal_age / self.consensus_window_ms)
            notional_score = min(1.0, math.log10(max(1, total_notional)) / 6.0)
            wallet_score = min(1.0, len(wallets_seen) / 5.0)
            signal_strength = (
                0.30 * freshness +
                0.30 * market_prio +
                0.25 * wallet_score +
                0.15 * notional_score
            )

            import hashlib
            cluster_id = hashlib.sha256(
                f"{market_id}:{side}:{first_ms}".encode()
            ).hexdigest()[:16]

            cluster = ClusterSignal(
                market_id=market_id,
                side=side,
                wallet_count=len(wallets_seen),
                participating_wallets=list(wallets_seen.keys()),
                total_notional_usdc=total_notional,
                first_wallet_opened_ms=first_ms,
                last_wallet_opened_ms=last_ms,
                signal_age_ms=signal_age,
                avg_entry_price=avg_price,
                signal_strength=signal_strength,
                market_priority=market_prio,
                is_fresh=signal_age < 4_000,
                cluster_id=cluster_id,
            )
            clusters.append(cluster)

        clusters.sort(key=lambda c: c.signal_strength, reverse=True)
        return clusters

    def get_open_positions_snapshot(self) -> dict[str, list[WalletPosition]]:
        """Snapshot de toutes les positions ouvertes par wallet."""
        return {addr: list(pos.values()) for addr, pos in self._positions.items()}

    def clear_stale_opens(self, max_age_ms: int = 300_000) -> int:
        """Nettoyer les opens trop vieux (>5 min). Retourne le nombre supprimé."""
        now_ms = int(time.time() * 1000)
        cutoff = now_ms - max_age_ms
        removed = 0
        for key in list(self._recent_opens.keys()):
            before = len(self._recent_opens[key])
            self._recent_opens[key] = [e for e in self._recent_opens[key] if e[1] >= cutoff]
            removed += before - len(self._recent_opens[key])
            if not self._recent_opens[key]:
                del self._recent_opens[key]
        return removed
