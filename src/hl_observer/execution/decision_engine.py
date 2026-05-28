from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from hl_observer.config.settings import Settings
from sqlalchemy import select, desc
from hl_observer.copying.realtime_magic_score import (
    RealtimeCopyRiskConfig,
    RealtimeCopyScoreInput,
    score_realtime_copy_candidate,
)
from hl_observer.storage.models import PositionDeltaModel, MarketMetric
from hl_observer.wallets.delta_utils import copy_delta_action, copy_delta_direction, delta_event_time_ms

logger = logging.getLogger(__name__)

@dataclass
class VirtualPosition:
    wallet: str
    coin: str
    direction: str
    size: float
    avg_price: float
    entry_costs: float
    entry_at_ms: int
    source_delta_ids: list[str] = field(default_factory=list)

class UnifiedDecisionEngine:
    """Professionalized local simulation engine for fictive $1,000 capital.

    This engine is shared between live simulation and backtesting to ensure
    identical trading rules and cost modeling.
    """

    def __init__(self, settings: Settings, session_factory=None):
        self.settings = settings
        self.session_factory = session_factory
        self.sim_cfg = settings.paper_simulation
        self.starting_equity = self.sim_cfg.starting_equity
        self.base_fee_bps = 4.0

        # Internal state
        self.positions: dict[str, VirtualPosition] = {}
        self.ledger_events: list[dict[str, Any]] = []
        self.processed_keys: set[str] = set()
        self.running_equity = self.starting_equity
        self.high_water_mark = self.starting_equity
        self.total_costs = 0.0
        self.drawdown_stop_triggered = False

    def load_state(
        self,
        positions_raw: dict[str, dict[str, Any]],
        ledger_events: list[dict[str, Any]],
        processed_keys: set[str]
    ):
        for key, pos in positions_raw.items():
            self.positions[key] = VirtualPosition(
                wallet=pos["wallet_address"],
                coin=pos["coin"],
                direction=pos["direction"],
                size=float(pos["size"]),
                avg_price=float(pos["avg_price"]),
                entry_costs=float(pos["entry_costs"]),
                entry_at_ms=int(pos.get("entry_at_ms", 0)),
                source_delta_ids=pos.get("source_delta_ids", [])
            )
        self.ledger_events = list(ledger_events)
        self.processed_keys = set(processed_keys)

        # Re-calculate running equity and HWM from ledger
        self.running_equity = self.starting_equity
        self.high_water_mark = self.starting_equity
        self.total_costs = 0.0
        for event in self.ledger_events:
            self.total_costs += float(event.get("fee_cost_usdc") or 0.0)
            if event.get("status") == "LOCAL_REPLAY":
                self.running_equity += float(event.get("estimated_net_pnl_usdc") or 0.0)
                self.high_water_mark = max(self.high_water_mark, self.running_equity)

                # Check if DD stop was ever triggered
                dd_pct = (self.high_water_mark - self.running_equity) / self.high_water_mark * 100.0 if self.high_water_mark > 0 else 0
                if dd_pct >= self.sim_cfg.max_drawdown_stop_pct:
                    self.drawdown_stop_triggered = True

    def _pos_key(self, wallet: str, coin: str, direction: str) -> str:
        return f"{wallet.lower()}|{coin.upper()}|{direction.upper()}"

    def process_deltas(
        self,
        deltas: list[PositionDeltaModel],
        mid_prices: dict[str, float],
        now_ms: int
    ) -> dict[str, Any]:
        chronological = sorted(deltas, key=lambda x: int(x.exchange_ts or x.detected_at_ms or 0))

        for delta in chronological:
            dk = self._delta_key(delta)
            if dk in self.processed_keys:
                continue
            self.processed_keys.add(dk)

            self._execute_simulation_step(delta, mid_prices, now_ms)

        return self.get_summary(mid_prices)

    def _delta_key(self, row: PositionDeltaModel) -> str:
        if row.delta_hash:
            return f"hash:{row.delta_hash}"
        ts = int(row.exchange_ts or row.detected_at_ms or 0)
        return f"raw:{row.wallet_address.lower()}:{row.coin.upper()}:{ts}:{row.delta_type}:{row.delta_size}"

    def _get_market_metric(self, coin: str) -> dict[str, float]:
        if not self.session_factory:
            return {"spread_bps": 3.0, "depth_usdc": 100_000.0}

        try:
            with self.session_factory() as session:
                metric = session.scalar(
                    select(MarketMetric)
                    .where(MarketMetric.coin == coin.upper())
                    .order_by(desc(MarketMetric.computed_at_ms))
                    .limit(1)
                )
                if metric:
                    return {
                        "spread_bps": float(metric.spread_bps or 3.0),
                        "depth_usdc": float(metric.depth_usdc or 100_000.0)
                    }
        except Exception as e:
            logger.warning(f"Failed to fetch market metrics for {coin}: {e}")

        return {"spread_bps": 3.0, "depth_usdc": 100_000.0}

    def _calculate_dynamic_costs(self, coin: str, notional: float) -> float:
        """Calculate dynamic costs in BPS based on market liquidity."""
        metrics = self._get_market_metric(coin)
        spread_bps = metrics["spread_bps"]
        depth = metrics["depth_usdc"]

        # Slippage model: 0.1bps per 1% of depth consumed, or 5bps minimum for small trades
        depth_consumption = notional / depth if depth > 0 else 1.0
        slippage_bps = max(5.0, depth_consumption * 1000.0)

        total_bps = self.base_fee_bps + (spread_bps / 2.0) + slippage_bps
        return total_bps

    def _execute_simulation_step(self, delta: PositionDeltaModel, mid_prices: dict[str, float], now_ms: int):
        action = copy_delta_action(delta)
        direction = copy_delta_direction(delta, action)
        ts = delta_event_time_ms(delta)

        event: dict[str, Any] = {
            "delta_key": self._delta_key(delta),
            "wallet_address": delta.wallet_address,
            "coin": delta.coin,
            "leader_action": action,
            "leader_side": direction,
            "observed_at_ms": ts,
            "leader_price": delta.price,
            "bot_replay_action": "NO_TRADE",
            "status": "REFUSED",
            "reason": None,
            "paper_mode": "PAPER_LOCAL_MOCK_USDC",
        }

        if action == "UNKNOWN" or direction is None or delta.price is None or delta.price <= 0:
            event["reason"] = "AMBIGUOUS_OR_INVALID_PRICE"
            self.ledger_events.append(event)
            return

        key = self._pos_key(delta.wallet_address, delta.coin, direction)

        # Entry Logic
        if action in {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}:
            if self.drawdown_stop_triggered:
                event["reason"] = "MAX_DRAWDOWN_STOP_REACHED"
                self.ledger_events.append(event)
                return

            score = self._score_opportunity(delta, direction, mid_prices, now_ms)
            event.update(score)

            if not score.get("accepted"):
                event["reason"] = score.get("decision_reason", "REJECTED_BY_SCORING")
                self.ledger_events.append(event)
                return

            desired_notional = float(score.get("simulated_notional_usdt") or 0.0)
            if self._current_exposure() + desired_notional > self.sim_cfg.max_total_exposure:
                event["reason"] = "MAX_TOTAL_EXPOSURE_REACHED"
                self.ledger_events.append(event)
                return

            # Execute virtual entry
            current_cost_bps = self._calculate_dynamic_costs(delta.coin, desired_notional)
            cost = desired_notional * current_cost_bps / 10_000.0
            size = desired_notional / float(delta.price)

            prev = self.positions.get(key)
            if prev:
                new_size = prev.size + size
                avg_px = ((prev.avg_price * prev.size) + (float(delta.price) * size)) / new_size
                prev.size = new_size
                prev.avg_price = avg_px
                prev.entry_costs += cost
                prev.source_delta_ids.append(str(delta.id or "0"))
            else:
                if len(self.positions) >= self.sim_cfg.max_open_trades:
                    event["reason"] = "MAX_OPEN_TRADES_REACHED"
                    self.ledger_events.append(event)
                    return
                self.positions[key] = VirtualPosition(
                    wallet=delta.wallet_address,
                    coin=delta.coin,
                    direction=direction,
                    size=size,
                    avg_price=float(delta.price),
                    entry_costs=cost,
                    entry_at_ms=ts,
                    source_delta_ids=[str(delta.id or "0")]
                )

            self.running_equity -= cost
            self.total_costs += cost
            self._update_drawdown()

            event.update({
                "bot_replay_action": "PAPER_ENTRY" if not prev else "PAPER_ADD",
                "status": "LOCAL_REPLAY",
                "estimated_net_pnl_usdc": -cost,
                "fee_cost_usdc": cost,
                "reason": "SIMULATED_LOCAL_FOLLOW",
            })
            self.ledger_events.append(event)
            return

        # Exit Logic
        if action in {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT"}:
            pos = self.positions.get(key)
            if not pos:
                event["reason"] = "NO_ACTIVE_POSITION_TO_EXIT"
                self.ledger_events.append(event)
                return

            delta_size = abs(float(delta.delta_size or delta.fill_size or pos.size))
            close_size = pos.size if action.startswith("CLOSE") else min(pos.size, delta_size)

            if direction == "LONG":
                gross_pnl = (float(delta.price) - pos.avg_price) * close_size
            else:
                gross_pnl = (pos.avg_price - float(delta.price)) * close_size

            current_cost_bps = self._calculate_dynamic_costs(delta.coin, close_size * float(delta.price))
            exit_cost = close_size * float(delta.price) * current_cost_bps / 10_000.0
            net_pnl = gross_pnl - exit_cost

            pos.size -= close_size
            if pos.size <= 1e-10:
                self.positions.pop(key)

            self.running_equity += net_pnl
            self.total_costs += exit_cost
            self._update_drawdown()

            event.update({
                "bot_replay_action": "PAPER_EXIT" if pos.size <= 0 else "PAPER_REDUCE",
                "status": "LOCAL_REPLAY",
                "estimated_net_pnl_usdc": net_pnl,
                "gross_pnl_usdc": gross_pnl,
                "fee_cost_usdc": exit_cost,
                "reason": "SIMULATED_LOCAL_EXIT",
            })
            self.ledger_events.append(event)
            return

    def _score_opportunity(self, delta: PositionDeltaModel, direction: str, mid_prices: dict[str, float], now_ms: int) -> dict:
        ts = int(delta.exchange_ts or delta.detected_at_ms or 0)
        age_ms = max(0, now_ms - ts)
        confidence = float(delta.confidence_score or 0.5)

        # Mocking some metrics for the score engine
        leader_edge = 18.0 + confidence * 34.0
        current_mid = mid_prices.get(delta.coin.upper())

        rt_cfg = RealtimeCopyRiskConfig(
            min_edge_required_bps=self.settings.risk.min_edge_required_bps,
            starting_equity_usdt=self.starting_equity,
            max_position_notional_usdt=self.sim_cfg.max_position_notional,
            max_total_exposure_usdt=self.sim_cfg.max_total_exposure,
            base_risk_fraction=self.sim_cfg.max_risk_per_trade_pct / 100.0,
        )

        score = score_realtime_copy_candidate(
            RealtimeCopyScoreInput(
                action_type="OPEN", # Simplified for engine
                direction=direction,
                leader_expected_edge_bps=leader_edge,
                leader_consistency_factor=0.85,
                signal_age_ms=age_ms,
                consensus_wallets=1,
                liquidity_score=0.8,
                leader_score=confidence * 100.0,
                leader_reference_price=float(delta.price),
                current_mid=current_mid,
                leader_notional_usdt=abs(float(delta.delta_notional_usdc or 0)),
                current_open_exposure_usdt=self._current_exposure(),
                current_open_positions=len(self.positions),
                max_open_positions=self.sim_cfg.max_open_trades,
            ),
            config=rt_cfg
        )

        return {
            "accepted": score.accepted,
            "decision_reason": "|".join(score.refusal_reasons) if score.refusal_reasons else "EDGE_OK",
            "simulated_notional_usdt": score.simulated_notional_usdt,
            "edge_remaining_bps": score.edge_remaining_bps,
            "risk_score": score.risk_score,
            "opportunity_score": score.opportunity_score,
        }

    def _current_exposure(self) -> float:
        return sum(p.size * p.avg_price for p in self.positions.values())

    def _update_drawdown(self):
        self.high_water_mark = max(self.high_water_mark, self.running_equity)
        dd_pct = (self.high_water_mark - self.running_equity) / self.high_water_mark * 100.0
        if dd_pct >= self.sim_cfg.max_drawdown_stop_pct:
            self.drawdown_stop_triggered = True

    def get_summary(self, mid_prices: dict[str, float]) -> dict[str, Any]:
        unrealized = 0.0
        open_pos_list = []
        for pos in self.positions.values():
            mark = mid_prices.get(pos.coin.upper(), pos.avg_price)
            pnl = (mark - pos.avg_price) * pos.size if pos.direction == "LONG" else (pos.avg_price - mark) * pos.size
            unrealized += pnl
            open_pos_list.append({
                "wallet": pos.wallet,
                "coin": pos.coin,
                "direction": pos.direction,
                "size": pos.size,
                "avg_price": pos.avg_price,
                "unrealized_pnl": pnl
            })

        net_pnl = (self.running_equity - self.starting_equity) + unrealized

        return {
            "starting_equity": self.starting_equity,
            "current_equity": self.running_equity + unrealized,
            "realized_pnl": self.running_equity - self.starting_equity,
            "unrealized_pnl": unrealized,
            "net_pnl": net_pnl,
            "total_costs": self.total_costs,
            "drawdown_pct": (self.high_water_mark - (self.running_equity + unrealized)) / self.high_water_mark * 100.0 if self.high_water_mark > 0 else 0,
            "drawdown_stop_triggered": self.drawdown_stop_triggered,
            "open_positions": open_pos_list,
            "ledger_events": self.ledger_events[-1000:],
            "reproduced_entries": sum(1 for e in self.ledger_events if any(k in e.get("bot_replay_action", "") for k in ["ENTRY", "ADD"])),
            "reproduced_exits": sum(1 for e in self.ledger_events if any(k in e.get("bot_replay_action", "") for k in ["EXIT", "REDUCE"])),
            "refused_count": sum(1 for e in self.ledger_events if e.get("status") == "REFUSED"),
        }
