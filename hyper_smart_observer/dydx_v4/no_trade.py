"""
Moteur de refus NO_TRADE dYdX v4.

Chaque refus est journalisé avec:
- raison typée
- detail technique
- impact estimé
- mode simulation

NO_TRADE est une BONNE décision si le trade aurait été mauvais.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Optional

from hyper_smart_observer.dydx_v4.models import (
    NoTradeDecision,
    NoTradeReason,
    SimulationMode,
)

logger = logging.getLogger(__name__)


@dataclass
class NoTradeReport:
    """Rapport de synthèse NO_TRADE."""
    total_refused: int
    by_reason: dict[str, int]
    top_reason: Optional[str]
    oldest_decision_ms: Optional[int]
    newest_decision_ms: Optional[int]

    def summary_text(self) -> str:
        lines = [
            f"NO_TRADE Report: {self.total_refused} refus totaux",
            f"Top raison: {self.top_reason}",
        ]
        for reason, count in sorted(self.by_reason.items(), key=lambda x: -x[1]):
            lines.append(f"  {reason}: {count}")
        return "\n".join(lines)


class DydxNoTradeEngine:
    """
    Journalise et analyse les décisions NO_TRADE.

    NO_TRADE = bonne décision si le trade aurait généré edge_remaining < 0.
    """

    def __init__(self, storage: Optional[Any] = None) -> None:  # noqa: F821
        self._decisions: list[NoTradeDecision] = []
        self._storage = storage  # DydxStorage optionnel

    def record(
        self,
        reason: NoTradeReason,
        account_address: Optional[str] = None,
        market_id: Optional[str] = None,
        detail: str = "",
        signal_candidate_id: Optional[str] = None,
        simulation_mode: SimulationMode = SimulationMode.LIVE,
    ) -> NoTradeDecision:
        """Enregistrer une décision NO_TRADE."""
        now_ms = int(time.time() * 1000)
        decision_id = hashlib.sha256(
            f"{reason.value}:{account_address}:{market_id}:{now_ms}".encode()
        ).hexdigest()[:24]

        dec = NoTradeDecision(
            decision_id=decision_id,
            reason=reason,
            signal_candidate_id=signal_candidate_id,
            account_address=account_address,
            market_id=market_id,
            detail=detail,
            timestamp_ms=now_ms,
            simulation_mode=simulation_mode,
        )

        self._decisions.append(dec)
        logger.debug("NO_TRADE %s: %s", reason.value, detail)

        if self._storage:
            try:
                self._storage.insert_no_trade(dec)
            except Exception as e:
                logger.error("no_trade storage error: %s", e)

        return dec

    def report(self) -> NoTradeReport:
        """Générer un rapport de synthèse."""
        by_reason: dict[str, int] = {}
        oldest: Optional[int] = None
        newest: Optional[int] = None

        for d in self._decisions:
            by_reason[d.reason.value] = by_reason.get(d.reason.value, 0) + 1
            if oldest is None or d.timestamp_ms < oldest:
                oldest = d.timestamp_ms
            if newest is None or d.timestamp_ms > newest:
                newest = d.timestamp_ms

        top = max(by_reason.items(), key=lambda x: x[1])[0] if by_reason else None

        return NoTradeReport(
            total_refused=len(self._decisions),
            by_reason=by_reason,
            top_reason=top,
            oldest_decision_ms=oldest,
            newest_decision_ms=newest,
        )

    def recent(self, limit: int = 20) -> list[NoTradeDecision]:
        """Retourner les décisions récentes (plus récentes en premier)."""
        return sorted(self._decisions, key=lambda d: d.timestamp_ms, reverse=True)[:limit]

    def count_by_reason(self, reason: NoTradeReason) -> int:
        return sum(1 for d in self._decisions if d.reason == reason)

    @property
    def total(self) -> int:
        return len(self._decisions)

    def clear(self) -> None:
        """Vider le log en mémoire (ne supprime pas la DB)."""
        self._decisions.clear()


# Type alias
Any = object
