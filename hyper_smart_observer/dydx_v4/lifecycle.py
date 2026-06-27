"""
Moteur de lifecycle dYdX v4.

Clé: exchange|network|account|subaccount|market|side

Règles strictes:
- OPEN: crée une position locale seulement si tous les gates passent
- ADD: seulement si position locale existe et edge net positif
- REDUCE/CLOSE: seulement si position locale existe
- CLOSE orphelin: table orphan, jamais PnL live
- UNKNOWN: interdit signal et paper
- FLIP: CLOSE puis OPEN séparés si cohérent
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from hyper_smart_observer.dydx_v4.models import (
    LifecycleEvent,
    NormalizedFill,
    NormalizedPositionDelta,
    PositionSide,
    SimulationMode,
)
from hyper_smart_observer.dydx_v4.normalizer import infer_lifecycle

logger = logging.getLogger(__name__)


@dataclass
class LocalPosition:
    """Position locale tracée par le lifecycle engine."""
    position_key: str
    account_address: str
    subaccount_number: int
    market_id: str
    side: PositionSide
    size: float
    entry_price: float
    opened_at_ms: int
    updated_at_ms: int
    lifecycle_history: list[LifecycleEvent] = field(default_factory=list)
    fill_ids: list[str] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.size > 0


@dataclass
class LifecycleResult:
    """Résultat d'un événement lifecycle."""
    event: LifecycleEvent
    position_key: str
    accepted: bool
    reason: str
    size_before: float
    size_after: float
    is_orphan: bool = False
    delta: Optional[NormalizedPositionDelta] = None


class DydxLifecycleEngine:
    """
    Moteur de lifecycle pour positions dYdX v4.
    Maintient un état local des positions par clé.
    Ne jamais appeler une API de trading.
    """

    def __init__(self, network: str = "testnet") -> None:
        self.network = network
        self._positions: dict[str, LocalPosition] = {}
        self._orphan_events: list[LifecycleResult] = []

    def position_key(self, account_address, subaccount_number, market_id, side):
        return f"dydx_v4|{self.network}|{account_address}|{subaccount_number}|{market_id}|{side.value}"

    def get_position(self, account_address, subaccount_number, market_id, side):
        key = self.position_key(account_address, subaccount_number, market_id, side)
        return self._positions.get(key)

    def process_fill(self, fill, side, simulation_mode=None):
        """Traiter un fill et mettre à jour la position locale."""
        if simulation_mode is None:
            simulation_mode = SimulationMode.LIVE

        if side == PositionSide.UNKNOWN:
            return LifecycleResult(
                event=LifecycleEvent.UNKNOWN,
                position_key="",
                accepted=False,
                reason="UNKNOWN_SIDE",
                size_before=0,
                size_after=0,
            )

        key = self.position_key(
            fill.account_address, fill.subaccount_number, fill.market_id, side
        )
        existing = self._positions.get(key)
        size_before = existing.size if existing else 0.0

        # Détection orphan précoce: SELL sur LONG vide, BUY sur SHORT vide
        is_closing_direction = (
            (side == PositionSide.LONG and fill.side.value == "SELL") or
            (side == PositionSide.SHORT and fill.side.value == "BUY")
        )
        if is_closing_direction and not existing:
            logger.warning(
                "ORPHAN CLOSE (no position): key=%s fill_id=%s", key, fill.fill_id
            )
            result = LifecycleResult(
                event=LifecycleEvent.CLOSE,
                position_key=key,
                accepted=False,
                reason="ORPHAN_CLOSE_NO_LOCAL_POSITION",
                size_before=0,
                size_after=0,
                is_orphan=True,
            )
            self._orphan_events.append(result)
            return result

        # Calculer la nouvelle taille selon fill side et position side
        new_size = size_before
        if side == PositionSide.LONG:
            if fill.side.value == "BUY":
                new_size = size_before + fill.size
            else:
                new_size = size_before - fill.size
        else:  # SHORT
            if fill.side.value == "SELL":
                new_size = size_before + fill.size
            else:
                new_size = size_before - fill.size

        new_size = max(0.0, round(new_size, 8))
        lifecycle = infer_lifecycle(size_before, new_size, side)

        if lifecycle == LifecycleEvent.UNKNOWN:
            return LifecycleResult(
                event=LifecycleEvent.UNKNOWN,
                position_key=key,
                accepted=False,
                reason="LIFECYCLE_DELTA_UNKNOWN",
                size_before=size_before,
                size_after=new_size,
            )

        if lifecycle in (LifecycleEvent.CLOSE, LifecycleEvent.REDUCE) and not existing:
            logger.warning(
                "ORPHAN %s: key=%s fill_id=%s", lifecycle.value, key, fill.fill_id
            )
            result = LifecycleResult(
                event=lifecycle,
                position_key=key,
                accepted=False,
                reason=f"ORPHAN_{lifecycle.value}_NO_LOCAL_POSITION",
                size_before=0,
                size_after=0,
                is_orphan=True,
            )
            self._orphan_events.append(result)
            return result

        if lifecycle == LifecycleEvent.ADD and not existing:
            return LifecycleResult(
                event=LifecycleEvent.UNKNOWN,
                position_key=key,
                accepted=False,
                reason="ADD_WITHOUT_OPEN",
                size_before=0,
                size_after=new_size,
            )

        now_ms = int(time.time() * 1000)

        if lifecycle == LifecycleEvent.OPEN:
            pos = LocalPosition(
                position_key=key,
                account_address=fill.account_address,
                subaccount_number=fill.subaccount_number,
                market_id=fill.market_id,
                side=side,
                size=new_size,
                entry_price=fill.price,
                opened_at_ms=fill.created_at_ms,
                updated_at_ms=now_ms,
                lifecycle_history=[LifecycleEvent.OPEN],
                fill_ids=[fill.fill_id] if fill.fill_id else [],
            )
            self._positions[key] = pos

        elif lifecycle == LifecycleEvent.ADD:
            assert existing is not None
            total_notional = existing.size * existing.entry_price + fill.size * fill.price
            total_size = existing.size + fill.size
            new_entry = total_notional / total_size if total_size > 0 else existing.entry_price
            existing.size = new_size
            existing.entry_price = new_entry
            existing.updated_at_ms = now_ms
            existing.lifecycle_history.append(LifecycleEvent.ADD)
            if fill.fill_id:
                existing.fill_ids.append(fill.fill_id)

        elif lifecycle in (LifecycleEvent.REDUCE, LifecycleEvent.CLOSE):
            assert existing is not None
            existing.size = new_size
            existing.updated_at_ms = now_ms
            existing.lifecycle_history.append(lifecycle)
            if fill.fill_id:
                existing.fill_ids.append(fill.fill_id)
            if lifecycle == LifecycleEvent.CLOSE:
                del self._positions[key]

        delta = NormalizedPositionDelta(
            account_address=fill.account_address,
            subaccount_number=fill.subaccount_number,
            market_id=fill.market_id,
            side=side,
            lifecycle=lifecycle,
            size_delta=new_size - size_before,
            price=fill.price,
            timestamp_ms=fill.created_at_ms,
            fill_id=fill.fill_id,
        )

        return LifecycleResult(
            event=lifecycle,
            position_key=key,
            accepted=True,
            reason="LIFECYCLE_ACCEPTED",
            size_before=size_before,
            size_after=new_size,
            delta=delta,
        )

    def snapshot_all(self):
        """Retourner toutes les positions locales ouvertes."""
        return dict(self._positions)

    @property
    def orphan_count(self):
        return len(self._orphan_events)
