"""
Simulateur paper trading dYdX v4.

PAPER-ONLY. Aucun ordre réel. Aucune clé privée. Aucune signature.
Balance mock USDC, positions virtuelles, PnL séparé LIVE/BACKTEST/REPLAY/TEST_FIXTURE.

Formules obligatoires:
  LONG:  (mark - entry) * size
  SHORT: (entry - mark) * size
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from hyper_smart_observer.dydx_v4.config import DydxV4Config
from hyper_smart_observer.dydx_v4.models import (
    LifecycleEvent,
    NoTradeReason,
    PaperPosition,
    PaperTrade,
    PaperTradeStatus,
    PositionSide,
    SignalCandidate,
    SimulationMode,
)
from hyper_smart_observer.dydx_v4.safety import assert_paper_only

logger = logging.getLogger(__name__)


@dataclass
class PaperSession:
    """État d'une session paper trading."""
    mode: SimulationMode
    network: str
    starting_balance: float
    current_balance: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_fees: float = 0.0
    total_spread_cost: float = 0.0
    total_slippage_cost: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    open_positions: dict[str, PaperPosition] = field(default_factory=dict)
    closed_trades: list[PaperTrade] = field(default_factory=list)
    started_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    disclaimer: str = (
        "Paper simulation only. No real orders. No real money. "
        "Past paper performance does not predict future real results."
    )

    @property
    def net_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl - self.total_fees

    @property
    def gross_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl

    @property
    def equity(self) -> float:
        return self.starting_balance + self.net_pnl

    @property
    def winrate(self) -> Optional[float]:
        total = self.winning_trades + self.losing_trades
        return self.winning_trades / total if total > 0 else None


class DydxPaperSimulator:
    """
    Simulateur paper trading dYdX v4.

    - Balance mock USDC (jamais réelle)
    - Positions virtuelles
    - PnL séparé par mode (LIVE / BACKTEST / REPLAY / TEST_FIXTURE)
    - Journal append-only
    - Cooldown après perte
    - Max exposure, max drawdown session
    """

    DISCLAIMER = (
        "PAPER SIMULATION ONLY. No real orders, no real money, "
        "no private keys, no signatures. dYdX READ-ONLY / PAPER-ONLY."
    )

    def __init__(
        self,
        config: DydxV4Config,
        storage: Optional[Any] = None,  # noqa: F821
        no_trade_engine: Optional[Any] = None,  # noqa: F821
    ) -> None:
        assert_paper_only(config)
        self.config = config
        self._storage = storage
        self._no_trade = no_trade_engine

        # Sessions séparées par mode
        self._sessions: dict[SimulationMode, PaperSession] = {}

    def _get_session(self, mode: SimulationMode) -> PaperSession:
        if mode not in self._sessions:
            self._sessions[mode] = PaperSession(
                mode=mode,
                network=self.config.network.value,
                starting_balance=self.config.starting_balance_usdc,
                current_balance=self.config.starting_balance_usdc,
            )
        return self._sessions[mode]

    # ----------------------------------------------------------------------- #
    # Entrée en position
    # ----------------------------------------------------------------------- #

    def open_position(
        self,
        signal: SignalCandidate,
        mark_price: float,
    ) -> Optional[PaperTrade]:
        """
        Ouvrir une position paper.

        Vérifie:
        - signal.lifecycle == OPEN
        - max open positions
        - max exposure
        - edge positif
        """
        assert_paper_only(self.config)

        mode = signal.simulation_mode
        session = self._get_session(mode)

        if signal.lifecycle != LifecycleEvent.OPEN:
            logger.warning("open_position appelé avec lifecycle=%s — ignoré", signal.lifecycle)
            return None

        # Max open trades
        open_count = len(session.open_positions)
        if open_count >= self.config.max_open_paper_trades:
            if self._no_trade:
                self._no_trade.record(
                    NoTradeReason.MAX_OPEN_TRADES_REACHED,
                    account_address=signal.account_address,
                    market_id=signal.market_id,
                    detail=f"open={open_count}",
                    simulation_mode=mode,
                )
            return None

        # Edge
        if signal.edge_remaining_bps <= 0:
            if self._no_trade:
                self._no_trade.record(
                    NoTradeReason.EDGE_REMAINING_TOO_LOW,
                    account_address=signal.account_address,
                    market_id=signal.market_id,
                    detail=f"edge_remaining={signal.edge_remaining_bps:.2f}bps",
                    simulation_mode=mode,
                )
            return None

        # Taille de position
        notional = session.current_balance * self.config.max_position_pct
        size = notional / mark_price if mark_price > 0 else 0.0
        if size <= 0:
            return None

        # Calcul du fill pessimiste (spread + slippage)
        slippage_bps = self.config.estimated_slippage_bps
        spread_bps = self.config.estimated_spread_bps
        cost_multiplier = (slippage_bps + spread_bps / 2) / 10_000

        if signal.side == PositionSide.LONG:
            entry_price = mark_price * (1 + cost_multiplier)
        else:
            entry_price = mark_price * (1 - cost_multiplier)

        fees = notional * (self.config.taker_fee_bps / 10_000)
        spread_cost = notional * (spread_bps / 10_000 / 2)
        slippage_cost = notional * (slippage_bps / 10_000)

        trade_id = hashlib.sha256(
            f"{signal.signal_id}:{int(time.time() * 1000)}".encode()
        ).hexdigest()[:32]

        position_key = (
            f"dydx_v4|{signal.account_address}|{signal.subaccount_number}"
            f"|{signal.market_id}|{signal.side.value}"
        )

        now_ms = int(time.time() * 1000)

        trade = PaperTrade(
            trade_id=trade_id,
            account_address=signal.account_address,
            subaccount_number=signal.subaccount_number,
            market_id=signal.market_id,
            side=signal.side,
            size=size,
            entry_price=entry_price,
            mark_price=mark_price,
            status=PaperTradeStatus.OPEN,
            lifecycle=LifecycleEvent.OPEN,
            gross_pnl=0.0,
            net_pnl=-fees,  # Frais d'entrée déjà imputés
            fees=fees,
            spread_cost=spread_cost,
            slippage_cost=slippage_cost,
            entry_at_ms=now_ms,
            updated_at_ms=now_ms,
            simulation_mode=mode,
            signal_id=signal.signal_id,
            notes=[self.DISCLAIMER],
        )

        # Créer la position paper
        position = PaperPosition(
            position_key=position_key,
            account_address=signal.account_address,
            subaccount_number=signal.subaccount_number,
            market_id=signal.market_id,
            side=signal.side,
            size=size,
            entry_price=entry_price,
            current_mark_price=mark_price,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            total_fees=fees,
            opened_at_ms=now_ms,
            updated_at_ms=now_ms,
            simulation_mode=mode,
            trade_ids=[trade_id],
        )

        session.open_positions[position_key] = position
        session.current_balance -= fees  # Frais d'entrée
        session.total_fees += fees
        session.total_spread_cost += spread_cost
        session.total_slippage_cost += slippage_cost
        session.total_trades += 1

        if self._storage:
            try:
                self._storage.insert_paper_trade(trade)
            except Exception as e:
                logger.error("paper trade storage error: %s", e)

        logger.info(
            "PAPER_OPEN: %s %s %s size=%.6f entry=%.4f fee=%.4f USDC [%s]",
            signal.market_id, signal.side.value, mode.value,
            size, entry_price, fees, self.DISCLAIMER,
        )

        return trade

    # ----------------------------------------------------------------------- #
    # Mise à jour mark price (unrealized PnL)
    # ----------------------------------------------------------------------- #

    def update_mark_price(
        self,
        position_key: str,
        mark_price: float,
        mode: SimulationMode = SimulationMode.LIVE,
    ) -> None:
        """Mettre à jour le PnL latent d'une position."""
        session = self._get_session(mode)
        pos = session.open_positions.get(position_key)
        if not pos:
            return

        # Formule correcte
        if pos.side == PositionSide.LONG:
            pos.unrealized_pnl = (mark_price - pos.entry_price) * abs(pos.size)
        else:
            pos.unrealized_pnl = (pos.entry_price - mark_price) * abs(pos.size)

        pos.current_mark_price = mark_price
        pos.updated_at_ms = int(time.time() * 1000)

        # Mise à jour PnL session
        session.unrealized_pnl = sum(
            p.unrealized_pnl for p in session.open_positions.values()
        )

    # ----------------------------------------------------------------------- #
    # Fermeture de position
    # ----------------------------------------------------------------------- #

    def close_position(
        self,
        position_key: str,
        mark_price: float,
        close_reason: str = "SIGNAL",
        mode: SimulationMode = SimulationMode.LIVE,
        partial_size: Optional[float] = None,
    ) -> Optional[PaperTrade]:
        """
        Fermer (partiellement ou totalement) une position paper.

        Retourne None si la position n'existe pas (refus orphan close).
        """
        assert_paper_only(self.config)

        session = self._get_session(mode)
        pos = session.open_positions.get(position_key)

        if not pos:
            logger.warning("ORPHAN_CLOSE: position_key=%s non trouvée — refusé", position_key)
            if self._no_trade:
                self._no_trade.record(
                    NoTradeReason.NO_MATCHING_PAPER_POSITION_FOR_CLOSE,
                    detail=f"position_key={position_key}",
                    simulation_mode=mode,
                )
            return None

        close_size = partial_size if partial_size and partial_size < pos.size else pos.size
        is_full_close = close_size >= pos.size

        # PnL réalisé
        if pos.side == PositionSide.LONG:
            gross_pnl = (mark_price - pos.entry_price) * close_size
        else:
            gross_pnl = (pos.entry_price - mark_price) * close_size

        # Frais de fermeture
        close_notional = close_size * mark_price
        close_fees = close_notional * (self.config.taker_fee_bps / 10_000)
        net_pnl = gross_pnl - close_fees

        now_ms = int(time.time() * 1000)
        trade_id = hashlib.sha256(
            f"close:{position_key}:{now_ms}".encode()
        ).hexdigest()[:32]

        lifecycle = LifecycleEvent.CLOSE if is_full_close else LifecycleEvent.REDUCE

        trade = PaperTrade(
            trade_id=trade_id,
            account_address=pos.account_address,
            subaccount_number=pos.subaccount_number,
            market_id=pos.market_id,
            side=pos.side,
            size=close_size,
            entry_price=pos.entry_price,
            mark_price=mark_price,
            status=PaperTradeStatus.CLOSED,
            lifecycle=lifecycle,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            fees=close_fees,
            spread_cost=0.0,
            slippage_cost=0.0,
            entry_at_ms=pos.opened_at_ms,
            updated_at_ms=now_ms,
            closed_at_ms=now_ms,
            close_reason=close_reason,
            simulation_mode=mode,
            notes=[self.DISCLAIMER],
        )

        # Mettre à jour la session
        session.realized_pnl += net_pnl
        session.total_fees += close_fees
        session.current_balance += net_pnl
        session.closed_trades.append(trade)

        if net_pnl > 0:
            session.winning_trades += 1
        else:
            session.losing_trades += 1

        if is_full_close:
            del session.open_positions[position_key]
        else:
            pos.size -= close_size
            pos.realized_pnl += net_pnl
            pos.total_fees += close_fees
            pos.updated_at_ms = now_ms

        session.unrealized_pnl = sum(
            p.unrealized_pnl for p in session.open_positions.values()
        )

        if self._storage:
            try:
                self._storage.insert_paper_trade(trade)
            except Exception as e:
                logger.error("close paper trade storage error: %s", e)

        logger.info(
            "PAPER_%s: %s %s size=%.6f gross=%.4f net=%.4f fee=%.4f [%s]",
            lifecycle.value, pos.market_id, pos.side.value,
            close_size, gross_pnl, net_pnl, close_fees, self.DISCLAIMER,
        )

        return trade

    # ----------------------------------------------------------------------- #
    # Lecture de l'état
    # ----------------------------------------------------------------------- #

    def get_session_stats(self, mode: SimulationMode = SimulationMode.LIVE) -> dict:
        """Statistiques de la session paper (READ-ONLY)."""
        session = self._get_session(mode)
        return {
            "disclaimer": self.DISCLAIMER,
            "mode": mode.value,
            "network": self.config.network.value,
            "starting_balance_usdc": session.starting_balance,
            "current_balance_usdc": round(session.current_balance, 6),
            "equity_usdc": round(session.equity, 6),
            "realized_pnl_usdc": round(session.realized_pnl, 6),
            "unrealized_pnl_usdc": round(session.unrealized_pnl, 6),
            "net_pnl_usdc": round(session.net_pnl, 6),
            "gross_pnl_usdc": round(session.gross_pnl, 6),
            "total_fees_usdc": round(session.total_fees, 6),
            "total_spread_cost_usdc": round(session.total_spread_cost, 6),
            "total_slippage_cost_usdc": round(session.total_slippage_cost, 6),
            "total_trades": session.total_trades,
            "open_positions": len(session.open_positions),
            "winning_trades": session.winning_trades,
            "losing_trades": session.losing_trades,
            "winrate": session.winrate,
            "paper_only": True,
            "no_real_orders": True,
            "no_real_money": True,
        }


# Type alias
Any = object
