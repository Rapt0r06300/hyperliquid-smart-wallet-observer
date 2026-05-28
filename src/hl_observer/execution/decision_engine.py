from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

from hl_observer.copying.realtime_magic_score import (
    RealtimeCopyRiskConfig,
    RealtimeCopyScoreInput,
    score_realtime_copy_candidate,
)
from hl_observer.paper.pessimistic_fill_model import pessimistic_fill_price
from hl_observer.paper.partial_fill_model import partial_fill_ratio


class SimulationConfig(BaseModel):
    """Professional configuration for the Unified Decision Engine."""
    risk_config: RealtimeCopyRiskConfig
    starting_equity_usdt: float = 1000.0
    max_position_notional_usdt: float = 50.0
    max_open_positions: int = 20
    consensus_window_ms: int = 300_000
    cost_bps: float = 12.0
    min_edge_required_bps: float = 8.0

    # Scenarios requested by user
    mode: Literal["WS_LIKE", "POLLING_60S", "POLLING_300S"] = "WS_LIKE"
    open_only: bool = False
    consensus_required: bool = False
    strict_edge: bool = False


class SimulationState(BaseModel):
    """Persistent or transient state of a simulation session."""
    virtual_positions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    ledger_events: list[dict[str, Any]] = Field(default_factory=list)
    processed_delta_keys: set[str] = Field(default_factory=set)
    equity_usdt: float = 1000.0
    starting_equity_usdt: float = 1000.0

    # Professional metrics tracking
    total_signals: int = 0
    executed_entries: int = 0
    executed_exits: int = 0
    refused_signals: int = 0
    total_fees_usdc: float = 0.0
    partial_fills_count: int = 0
    missed_fills_count: int = 0


class UnifiedDecisionEngine:
    """A centralized, pessimistic decision engine shared by live simulations and historical replays.

    Ensures that 'live simulation == replay simulation' by using the exact same rules,
    costs, and fill models.
    """

    def __init__(self, config: SimulationConfig) -> None:
        self.config = config

    def process_delta(
        self,
        row: Any,
        current_ms: int,
        mid_prices: dict[str, float],
        state: SimulationState,
        all_deltas: list[Any],
    ) -> dict[str, Any] | None:
        """Evaluates a leader delta and updates the simulation state accordingly."""
        state.total_signals += 1

        action = self._detect_action(row)
        direction = self._detect_direction(row, action)

        if action == "UNKNOWN" or direction is None:
            return self._record_refusal(row, action, direction, current_ms, "UNKNOWN_DELTA", state)

        if row.price is None or row.price <= 0:
            return self._record_refusal(row, action, direction, current_ms, "PRICE_MISSING", state)

        key = self._encode_position_key(row.wallet_address, row.coin, direction)
        metrics = self._calculate_metrics(row, direction, current_ms, mid_prices, state, all_deltas)

        # Tracking missed fills (stale signals)
        if "STALE_SIGNAL" in str(metrics.get("decision_reason", "")):
            state.missed_fills_count += 1

        if action in {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}:
            if metrics["decision_reason"] != "EDGE_OK_FOR_LOCAL_SIMULATION":
                return self._record_refusal(row, action, direction, current_ms, str(metrics["decision_reason"]), state, metrics)

            if self.config.consensus_required and metrics.get("consensus_wallets", 0) < 2:
                 return self._record_refusal(row, action, direction, current_ms, "CONSENSUS_REQUIRED", state, metrics)

            return self._execute_entry(row, action, direction, key, metrics, state)

        if action in {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT"}:
            if self.config.open_only:
                 return self._record_refusal(row, action, direction, current_ms, "OPEN_ONLY_MODE", state, metrics)

            return self._execute_exit(row, action, direction, key, metrics, state)

        return self._record_refusal(row, action, direction, current_ms, "UNSUPPORTED_DELTA", state, metrics)

    def _detect_action(self, row: Any) -> str:
        # Standard logic for Hyperliquid deltas
        raw = f"{getattr(row, 'delta_type', '') or ''} {getattr(row, 'action', '') or ''} {getattr(row, 'previous_side', '') or ''} {getattr(row, 'new_side', '') or ''} {getattr(row, 'side', '') or ''}".lower()
        previous = (getattr(row, 'previous_side', '') or "").lower()
        new = (getattr(row, 'new_side', '') or getattr(row, 'side', '') or "").lower()

        if "open" in raw:
            if "short" in raw or new == "short" or getattr(row, 'current_size', 0) < 0: return "OPEN_SHORT"
            return "OPEN_LONG"
        if "add" in raw or "increase" in raw: return "ADD"
        if "reduce" in raw: return "REDUCE"
        if "close" in raw:
            if "short" in raw or previous == "short" or getattr(row, 'previous_size', 0) < 0: return "CLOSE_SHORT"
            return "CLOSE_LONG"
        return "UNKNOWN"

    def _detect_direction(self, row: Any, action: str) -> str | None:
        if action == "OPEN_LONG": return "LONG"
        if action == "OPEN_SHORT": return "SHORT"
        if action == "ADD":
            if getattr(row, 'current_size', 0) > 0 or "long" in (getattr(row, 'new_side', '') or "").lower(): return "LONG"
            if getattr(row, 'current_size', 0) < 0 or "short" in (getattr(row, 'new_side', '') or "").lower(): return "SHORT"
        if action in {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT"}:
            if action == "CLOSE_LONG": return "LONG"
            if action == "CLOSE_SHORT": return "SHORT"
            if getattr(row, 'previous_size', 0) > 0: return "LONG"
            if getattr(row, 'previous_size', 0) < 0: return "SHORT"
        return None

    def _calculate_metrics(
        self, row: Any, direction: str, current_ms: int, mid_prices: dict[str, float], state: SimulationState, all_deltas: list[Any]
    ) -> dict[str, Any]:
        obs_at = int(getattr(row, 'exchange_ts', 0) or getattr(row, 'detected_at_ms', 0) or 0)
        age_ms = max(0, current_ms - obs_at) if obs_at > 0 else 0

        # Consensus: how many wallets are doing the same thing?
        consensus_count = self._calculate_consensus(row, direction, all_deltas)

        confidence = max(0.0, min(1.0, float(getattr(row, 'confidence_score', 0.5) or 0.5)))
        leader_edge = 18.0 + confidence * 34.0 + min(24.0, (consensus_count - 1) * 8.0)
        if self.config.strict_edge: leader_edge *= 0.8

        leader_size = abs(float(getattr(row, 'delta_size', 0.0) or getattr(row, 'fill_size', 0.0) or 0.0))
        leader_ntl = abs(float(getattr(row, 'delta_notional_usdc', 0.0) or (leader_size * float(getattr(row, 'price', 0.0) or 0.0))))
        liq_score = max(0.2, min(1.0, leader_ntl / 2500.0))

        mid = mid_prices.get(str(row.coin).upper())
        exposure = sum(abs(p["size"] * p["avg_price"]) for p in state.virtual_positions.values())

        inp = RealtimeCopyScoreInput(
            action_type=self._detect_action(row), direction=direction,
            leader_expected_edge_bps=leader_edge, leader_consistency_factor=0.72 + confidence * 0.28,
            signal_age_ms=age_ms, consensus_wallets=consensus_count, liquidity_score=liq_score, leader_score=confidence * 100.0,
            leader_reference_price=float(row.price or 0.0), current_mid=mid, leader_notional_usdt=leader_ntl,
            current_open_exposure_usdt=exposure, current_open_positions=len(state.virtual_positions), max_open_positions=self.config.max_open_positions,
        )
        score = score_realtime_copy_candidate(inp, config=self.config.risk_config)
        reason = "EDGE_OK_FOR_LOCAL_SIMULATION" if score.accepted else "|".join(score.refusal_reasons or ["REJECT_NO_TRADE"])

        return {
            "signal_age_ms": age_ms, "signal_freshness_score": score.signal_freshness_score, "consensus_wallets": score.consensus_wallets,
            "leader_expected_edge_bps": score.leader_expected_edge_bps or 0.0, "leader_consistency_factor": score.leader_consistency_factor,
            "copy_degradation_bps": score.copy_degradation_bps, "edge_remaining_bps": score.edge_remaining_bps or -9999.0,
            "opportunity_score": score.opportunity_score, "risk_score": score.risk_score, "simulated_notional_usdt": score.simulated_notional_usdt,
            "decision_reason": reason, "adverse_price_move_bps": score.adverse_price_move_bps,
        }

    def _calculate_consensus(self, row: Any, direction: str, all_deltas: list[Any]) -> int:
        obs_at = int(getattr(row, 'exchange_ts', 0) or getattr(row, 'detected_at_ms', 0) or 0)
        if obs_at <= 0: return 1
        start = obs_at - self.config.consensus_window_ms
        wallets = {
            item.wallet_address.lower() for item in all_deltas
            if item.coin.upper() == row.coin.upper() and start <= int(getattr(item, 'exchange_ts', 0) or getattr(item, 'detected_at_ms', 0) or 0) <= obs_at
            and self._detect_direction(item, self._detect_action(item)) == direction
            and self._detect_action(item) in {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}
        }
        return max(1, len(wallets))

    def _execute_entry(self, row: Any, action: str, direction: str, key: str, metrics: dict[str, Any], state: SimulationState) -> dict[str, Any]:
        notional = float(metrics.get("simulated_notional_usdt") or 0.0)
        if notional <= 0: return self._record_refusal(row, action, direction, 0, "MAX_EXPOSURE_REACHED", state, metrics)

        depth = getattr(row, 'orderbook_depth_usdc', 0.0)
        fill_ratio = 1.0
        if depth > 0:
            fill_ratio = partial_fill_ratio(notional, depth)
            if fill_ratio < 1.0:
                state.partial_fills_count += 1
                notional *= fill_ratio
                metrics["partial_fill_warning"] = f"Partial fill: {round(fill_ratio * 100, 2)}%"

        px = pessimistic_fill_price("buy" if direction == "LONG" else "sell", float(row.price), self.config.risk_config.spread_bps, self.config.risk_config.slippage_bps)
        sz, cost = notional / px, notional * self.config.cost_bps / 10000.0
        state.total_fees_usdc += cost
        state.executed_entries += 1

        prev = state.virtual_positions.get(key, {"size": 0.0, "avg_price": 0.0, "entry_costs": 0.0})
        bot_action = "PAPER_ENTRY_REPLAYED" if "OPEN" in action else "PAPER_ADD_REPLAYED"
        note = "LOCAL_REPLAY_ONLY_EDGE_GATE_REQUIRED_FOR_REAL_PAPER_INTENT"

        if "ADD" in action and prev["size"] <= 0:
            if len(state.virtual_positions) >= self.config.max_open_positions:
                return self._record_refusal(row, action, direction, 0, "MAX_VIRTUAL_POSITIONS_REACHED", state, metrics)
            bot_action, note = "PAPER_JOIN_ADD_AS_ENTRY", "JOINED_LEADER_ADD_WITH_SMALL_CAPPED_POSITION"

        new_sz = prev["size"] + sz
        avg_px = (((prev["avg_price"] * prev["size"]) + (px * sz)) / new_sz if new_sz > 0 else px)
        state.virtual_positions[key] = {"size": new_sz, "avg_price": avg_px, "entry_costs": prev["entry_costs"] + cost}

        event = {
            "delta_key": self._delta_key(row), "wallet_address": row.wallet_address, "coin": row.coin, "leader_action": action, "leader_side": direction,
            "observed_at_ms": int(getattr(row, 'exchange_ts', 0) or getattr(row, 'detected_at_ms', 0) or 0), "leader_price": row.price, "fill_price": px,
            "bot_replay_action": bot_action, "status": "LOCAL_REPLAY", "estimated_net_pnl_usdc": round(-cost, 6), "fee_cost_usdc": round(cost, 6),
            "bot_position_size_after": round(new_sz, 10), "copied_notional_usdt": round(notional, 6), "reason": note, "research_only": True,
        }
        event.update(metrics)
        state.ledger_events.append(event)
        return event

    def _execute_exit(self, row: Any, action: str, direction: str, key: str, metrics: dict[str, Any], state: SimulationState) -> dict[str, Any]:
        prev = state.virtual_positions.get(key)
        if prev is None or prev["size"] <= 0: return self._record_refusal(row, action, direction, 0, "NO_MATCHING_PAPER_POSITION_FOR_CLOSE", state, metrics)

        px = pessimistic_fill_price("sell" if direction == "LONG" else "buy", float(row.price), self.config.risk_config.spread_bps, self.config.risk_config.slippage_bps)
        ld_sz = abs(float(getattr(row, 'delta_size', 0.0) or getattr(row, 'fill_size', 0.0) or 0.0))
        cls_sz = prev["size"] if "CLOSE" in action or ld_sz <= 0 else min(prev["size"], ld_sz)

        gross_pnl = (px - prev["avg_price"]) * cls_sz if direction == "LONG" else (prev["avg_price"] - px) * cls_sz
        cost = cls_sz * px * self.config.cost_bps / 10000.0
        net_pnl = gross_pnl - cost

        state.total_fees_usdc += cost
        state.executed_exits += 1
        state.equity_usdt += net_pnl  # Realize PnL and update equity

        rem_sz = max(0.0, prev["size"] - cls_sz)
        if rem_sz <= 1e-12: state.virtual_positions.pop(key, None)
        else:
            # Correct cost scaling for partial reductions
            new_entry_costs = prev["entry_costs"] * (rem_sz / prev["size"])
            state.virtual_positions[key] = {"size": rem_sz, "avg_price": prev["avg_price"], "entry_costs": new_entry_costs}

        event = {
            "delta_key": self._delta_key(row), "wallet_address": row.wallet_address, "coin": row.coin, "leader_action": action, "leader_side": direction,
            "observed_at_ms": int(getattr(row, 'exchange_ts', 0) or getattr(row, 'detected_at_ms', 0) or 0), "leader_price": row.price, "fill_price": px,
            "bot_replay_action": "PAPER_CLOSE_REPLAYED" if "CLOSE" in action else "PAPER_REDUCE_REPLAYED", "status": "LOCAL_REPLAY",
            "estimated_net_pnl_usdc": round(net_pnl, 6), "gross_pnl_usdc": round(gross_pnl, 6), "fee_cost_usdc": round(cost, 6),
            "bot_position_size_after": round(rem_sz, 10), "copied_notional_usdt": round(cls_sz * px, 6), "reason": "LOCAL_REPLAY_ONLY_NOT_AN_ORDER", "research_only": True,
        }
        event.update(metrics)
        state.ledger_events.append(event)
        return event

    def _record_refusal(self, row: Any, action: str, direction: str | None, current_ms: int, reason: str, state: SimulationState, metrics: dict | None = None) -> dict[str, Any]:
        state.refused_signals += 1
        event = {
            "delta_key": self._delta_key(row), "wallet_address": row.wallet_address, "coin": row.coin, "leader_action": action, "leader_side": direction,
            "observed_at_ms": int(getattr(row, 'exchange_ts', 0) or getattr(row, 'detected_at_ms', 0) or 0), "leader_price": row.price, "bot_replay_action": "NO_TRADE",
            "status": "REFUSED", "reason": reason, "research_only": True,
        }
        if metrics: event.update(metrics)
        state.ledger_events.append(event)
        return event

    def _encode_position_key(self, wallet: str, coin: str, direction: str) -> str:
        return f"{wallet.lower()}|{coin.upper()}|{direction.upper()}"

    def _delta_key(self, row: Any) -> str:
        if hasattr(row, 'delta_hash') and row.delta_hash: return f"hash:{row.delta_hash}"
        if hasattr(row, 'id') and row.id is not None: return f"id:{row.id}"
        obs_at = int(getattr(row, 'exchange_ts', 0) or getattr(row, 'detected_at_ms', 0) or 0)
        return f"raw:{row.wallet_address.lower()}:{row.coin.upper()}:{obs_at}:{getattr(row, 'delta_type', '')}:{getattr(row, 'delta_size', '')}:{getattr(row, 'price', '')}"
