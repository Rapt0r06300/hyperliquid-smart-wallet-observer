"""
Backtest/Replay dYdX v4 — strictement séparé du PnL LIVE.

Le PnL BACKTEST ne doit jamais polluer le PnL LIVE.
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
    NormalizedFill,
    PositionSide,
    SimulationMode,
)

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """Trade rejoué en backtest."""
    fill_id: str
    market_id: str
    side: PositionSide
    size: float
    entry_price: float
    exit_price: Optional[float]
    gross_pnl: float
    fees: float
    net_pnl: float
    lifecycle: LifecycleEvent
    entry_at_ms: int
    exit_at_ms: Optional[int]
    simulation_mode: SimulationMode = SimulationMode.BACKTEST


@dataclass
class BacktestResult:
    """Résultats d'un run de backtest."""
    run_id: str
    network: str
    start_ms: int
    end_ms: int
    total_trades: int = 0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    total_fees: float = 0.0
    winning_trades: int = 0
    losing_trades: int = 0
    max_drawdown: float = 0.0
    winrate: Optional[float] = None
    trades: list[BacktestTrade] = field(default_factory=list)
    disclaimer: str = (
        "BACKTEST SIMULATION ONLY. No real orders, no real money. "
        "Historical backtest does not predict future performance."
    )

    def __post_init__(self) -> None:
        if self.total_trades > 0:
            self.winrate = self.winning_trades / self.total_trades


class DydxBacktester:
    """
    Backtest/Replay dYdX v4 sur fills historiques.

    - Mode BACKTEST: séparé du LIVE
    - Mode REPLAY: debug/recherche uniquement
    - TEST_FIXTURE: toujours exclu du PnL live
    """

    DISCLAIMER = (
        "BACKTEST SIMULATION ONLY. No real orders. No real money. "
        "Historical paper performance does not predict future results."
    )

    def __init__(self, config: DydxV4Config) -> None:
        self.config = config

    def run_on_fills(
        self,
        fills: list[NormalizedFill],
        mode: SimulationMode = SimulationMode.BACKTEST,
        delay_ms: int = 300_000,
        fee_bps: float = 5.0,
    ) -> BacktestResult:
        """
        Rejouer des fills historiques en simulation.

        Args:
            fills: fills triés par timestamp croissant
            mode: BACKTEST ou REPLAY (jamais LIVE dans cette méthode)
            delay_ms: délai simulé de copie (latence)
            fee_bps: frais taker en bps

        Returns:
            BacktestResult (jamais mélangé avec LIVE)
        """
        if mode == SimulationMode.LIVE:
            raise ValueError(
                "SAFETY: run_on_fills ne doit pas être appelé en mode LIVE. "
                "Utiliser DydxPaperSimulator pour le live."
            )

        run_id = hashlib.sha256(
            f"backtest:{mode.value}:{int(time.time() * 1000)}".encode()
        ).hexdigest()[:24]

        start_ms = fills[0].created_at_ms if fills else int(time.time() * 1000)
        end_ms = fills[-1].created_at_ms if fills else start_ms

        result = BacktestResult(
            run_id=run_id,
            network=self.config.network.value,
            start_ms=start_ms,
            end_ms=end_ms,
        )

        # Clé = account/subaccount/market (sans side)
        # Un seul côté actif par marché à la fois
        open_positions: dict[str, dict] = {}

        sorted_fills = sorted(fills, key=lambda f: f.created_at_ms)

        for fill in sorted_fills:
            key = f"{fill.account_address}/{fill.subaccount_number}/{fill.market_id}"
            effective_ts = fill.created_at_ms + delay_ms

            if key not in open_positions:
                # OPEN: BUY ouvre LONG, SELL ouvre SHORT
                side = PositionSide.LONG if fill.side.value == "BUY" else PositionSide.SHORT
                notional = fill.size * fill.price
                entry_fee = notional * (fee_bps / 10_000)
                open_positions[key] = {
                    "fill_id": fill.fill_id,
                    "entry_price": fill.price,
                    "size": fill.size,
                    "side": side,
                    "market_id": fill.market_id,
                    "entry_at_ms": effective_ts,
                    "entry_fee": entry_fee,
                }
            else:
                pos_side = open_positions[key]["side"]
                # SELL ferme LONG, BUY ferme SHORT
                is_close = (
                    (pos_side == PositionSide.LONG and fill.side.value == "SELL") or
                    (pos_side == PositionSide.SHORT and fill.side.value == "BUY")
                )
                if not is_close:
                    # ADD: même sens — mise à jour du prix moyen pondéré
                    entry = open_positions[key]
                    total_notional = entry["size"] * entry["entry_price"] + fill.size * fill.price
                    total_size = entry["size"] + fill.size
                    entry["entry_price"] = total_notional / total_size if total_size > 0 else entry["entry_price"]
                    entry["size"] = total_size
                    entry["entry_fee"] += fill.size * fill.price * (fee_bps / 10_000)
                    continue

                # CLOSE
                entry = open_positions.pop(key)
                side = pos_side

                # Formule PnL correcte
                if side == PositionSide.LONG:
                    gross = (fill.price - entry["entry_price"]) * entry["size"]
                else:
                    gross = (entry["entry_price"] - fill.price) * entry["size"]

                close_notional = entry["size"] * fill.price
                close_fee = close_notional * (fee_bps / 10_000)
                total_fee = entry["entry_fee"] + close_fee
                net = gross - total_fee

                bt_trade = BacktestTrade(
                    fill_id=fill.fill_id,
                    market_id=fill.market_id,
                    side=side,
                    size=entry["size"],
                    entry_price=entry["entry_price"],
                    exit_price=fill.price,
                    gross_pnl=gross,
                    fees=total_fee,
                    net_pnl=net,
                    lifecycle=LifecycleEvent.CLOSE,
                    entry_at_ms=entry["entry_at_ms"],
                    exit_at_ms=effective_ts,
                    simulation_mode=mode,
                )

                result.trades.append(bt_trade)
                result.gross_pnl += gross
                result.net_pnl += net
                result.total_fees += total_fee
                result.total_trades += 1
                if net > 0:
                    result.winning_trades += 1
                else:
                    result.losing_trades += 1

        # Max drawdown
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in result.trades:
            cumulative += t.net_pnl
            peak = max(peak, cumulative)
            dd = peak - cumulative
            max_dd = max(max_dd, dd)
        result.max_drawdown = max_dd

        if result.total_trades > 0:
            result.winrate = result.winning_trades / result.total_trades

        logger.info(
            "Backtest %s: mode=%s trades=%d net_pnl=%.4f disclaimer=%s",
            run_id, mode.value, result.total_trades, result.net_pnl, self.DISCLAIMER,
        )

        return result
