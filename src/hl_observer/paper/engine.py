from __future__ import annotations

import logging
import time
from collections import Counter
from typing import Any

from hl_observer.config.settings import Settings
from hl_observer.copying.realtime_magic_score import (
    RealtimeCopyRiskConfig,
    RealtimeCopyScoreInput,
    score_realtime_copy_candidate,
)
from hl_observer.storage.models import PositionDeltaModel, SourceHealth
from hl_observer.wallets.delta_utils import (
    copy_delta_action,
    copy_delta_direction,
    delta_event_time_ms,
)
from hl_observer.utils.time import now_ms

logger = logging.getLogger(__name__)

class SimulationEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cost_bps = 12.0
        self.min_edge_required_bps = 8.0
        self.max_signal_age_ms = 10 * 60_000
        self.consensus_window_ms = 5 * 60_000

    def calculate_global_health_score(self, health_map: dict[str, SourceHealth] | None) -> int:
        if not health_map:
            return 0

        weights = {
            "allMids": 4,
            "l2Book": 4,
            "hyperliquid_ws_public_trades": 4,
            "hyperliquid_info:userFills": 1,
            "position_deltas": 1
        }

        total_weight = 0
        weighted_score = 0

        for name, health in health_map.items():
            weight = weights.get(name, 1)
            total_weight += weight

            status_score = 0
            status = str(health.freshness_status).upper()
            if "FRESH" in status:
                status_score = 100
            elif "STALE" in status:
                status_score = 40
            elif "DELAYED" in status:
                status_score = 70
            elif "UNKNOWN" in status:
                status_score = 20

            if not health.is_consistent:
                status_score = 0

            weighted_score += status_score * weight

        if total_weight == 0:
            return 0
        return int(weighted_score / total_weight)

    def build_bot_simulation(
        self,
        deltas: list[PositionDeltaModel],
        *,
        mid_prices: dict[str, float] | None = None,
        starting_equity_usdt: float = 1000.0,
        max_position_notional_usdt: float = 50.0,
        max_open_positions: int = 20,
        max_events: int = 2_000,
        now_timestamp_ms: int | None = None,
        existing_positions: dict[str, dict[str, Any]] | None = None,
        existing_events: list[dict[str, Any]] | None = None,
        processed_delta_keys: set[str] | None = None,
        health_map: dict[str, SourceHealth] | None = None,
    ) -> dict[str, Any]:

        def encode_position_key(wallet: str, coin: str, direction: str) -> str:
            return f"{wallet.lower()}|{coin.upper()}|{direction.upper()}"

        def decode_position_key(value: str) -> tuple[str, str, str] | None:
            parts = value.split("|")
            if len(parts) != 3:
                return None
            return parts[0].lower(), parts[1].upper(), parts[2].upper()

        def delta_key(row: PositionDeltaModel) -> str:
            if row.delta_hash:
                return f"hash:{row.delta_hash}"
            if row.id is not None:
                return f"id:{row.id}"
            return (
                f"raw:{row.wallet_address.lower()}:{row.coin.upper()}:{delta_event_time_ms(row)}:"
                f"{row.delta_type}:{row.previous_size}:{row.new_size}:{row.delta_size}:{row.price}"
            )

        positions: dict[tuple[str, str, str], dict[str, float]] = {}
        for raw_key, raw_position in (existing_positions or {}).items():
            decoded = decode_position_key(str(raw_key))
            if decoded is None or not isinstance(raw_position, dict):
                continue
            positions[decoded] = {
                "size": float(raw_position.get("size") or 0.0),
                "avg_price": float(raw_position.get("avg_price") or 0.0),
                "entry_costs": float(raw_position.get("entry_costs") or 0.0),
            }

        ledger_events: list[dict[str, Any]] = [
            dict(row)
            for row in (existing_events or [])[-max_events:]
            if isinstance(row, dict)
        ]
        processed_keys = set(processed_delta_keys or set())
        current_ms = now_timestamp_ms or now_ms()

        realtime_score_config = RealtimeCopyRiskConfig(
            min_edge_required_bps=self.settings.risk.min_edge_required_bps if hasattr(self.settings, "risk") else 8.0,
            fee_bps=4.0,
            spread_bps=3.0,
            slippage_bps=5.0,
            max_signal_age_ms=self.max_signal_age_ms,
            starting_equity_usdt=starting_equity_usdt,
            max_position_notional_usdt=max_position_notional_usdt,
            max_total_exposure_usdt=max_position_notional_usdt * 4.0,
        )

        is_data_stale = False
        stale_sources = []
        if self.settings.adaptive_risk_filter.block_if_data_stale and health_map:
            for src_name, health in health_map.items():
                if not health.is_consistent:
                    is_data_stale = True
                    stale_sources.append(f"{src_name}:CONTRADICTORY")
                    continue

                if not health.is_heartbeat:
                    continue

                stale_threshold = self.settings.adaptive_risk_filter.stale_threshold_seconds
                dead_threshold = self.settings.adaptive_risk_filter.dead_threshold_seconds

                if src_name in {"allMids", "hyperliquid_ws_public_trades", "l2Book"}:
                    stale_threshold = getattr(self.settings.adaptive_risk_filter, "heartbeat_stale_threshold_seconds", 5)
                    dead_threshold = getattr(self.settings.adaptive_risk_filter, "heartbeat_dead_threshold_seconds", 30)

                age = health.seconds_since_last_event or 9999
                if age >= dead_threshold:
                    is_data_stale = True
                    stale_sources.append(f"{src_name}:DEAD({age}s)")
                elif age >= stale_threshold:
                    is_data_stale = True
                    stale_sources.append(f"{src_name}:STALE({age}s)")

        chronological = sorted(deltas, key=delta_event_time_ms)

        def current_open_exposure_usdt() -> float:
            return sum(abs(position["size"] * position["avg_price"]) for position in positions.values())

        def consensus_wallet_count(row: PositionDeltaModel, direction: str) -> int:
            window_ms = self.consensus_window_ms
            ts = delta_event_time_ms(row)
            others = [
                d for d in deltas
                if d.coin == row.coin
                and abs(delta_event_time_ms(d) - ts) <= window_ms
                and copy_delta_direction(d) == direction
            ]
            return len({d.wallet_address.lower() for d in others})

        def opportunity_metrics(row: PositionDeltaModel, direction: str) -> dict[str, float | int | str]:
            observed_at = delta_event_time_ms(row)
            age_ms = max(0, current_ms - observed_at) if observed_at > 0 else self.max_signal_age_ms
            consensus_count = consensus_wallet_count(row, direction)
            confidence = max(0.0, min(1.0, float(row.confidence_score or 0.5)))
            leader_expected_edge_bps = 18.0 + confidence * 34.0 + min(24.0, (consensus_count - 1) * 8.0)
            leader_size = abs(float(row.delta_size or row.fill_size or 0.0))
            leader_notional = abs(float(row.delta_notional_usdc or (leader_size * float(row.price or 0.0))))
            liquidity_score = max(0.2, min(1.0, leader_notional / 2_500.0))
            current_mid = (mid_prices or {}).get(str(row.coin).upper())
            score = score_realtime_copy_candidate(
                RealtimeCopyScoreInput(
                    action_type=copy_delta_action(row),
                    direction=direction,
                    leader_expected_edge_bps=leader_expected_edge_bps,
                    leader_consistency_factor=0.72 + confidence * 0.28,
                    signal_age_ms=age_ms,
                    consensus_wallets=consensus_count,
                    liquidity_score=liquidity_score,
                    leader_score=confidence * 100.0,
                    leader_reference_price=float(row.price or 0.0),
                    current_mid=current_mid,
                    leader_notional_usdt=leader_notional,
                    current_open_exposure_usdt=current_open_exposure_usdt(),
                    current_open_positions=len(positions),
                    max_open_positions=max_open_positions,
                ),
                config=realtime_score_config,
            )
            decision_reason = (
                "EDGE_OK_FOR_LOCAL_SIMULATION"
                if score.accepted
                else "|".join(score.refusal_reasons or ["REJECT_NO_TRADE"])
            )

            shadow_outcome_bps = 0.0
            if not score.accepted and current_mid and row.price:
                if direction == "LONG":
                    shadow_outcome_bps = (current_mid - float(row.price)) / float(row.price) * 10000.0
                else:
                    shadow_outcome_bps = (float(row.price) - current_mid) / float(row.price) * 10000.0

            return {
                "signal_age_ms": age_ms,
                "signal_freshness_score": score.signal_freshness_score,
                "consensus_wallets": score.consensus_wallets,
                "leader_expected_edge_bps": score.leader_expected_edge_bps or 0.0,
                "leader_consistency_factor": score.leader_consistency_factor,
                "consensus_factor": score.consensus_factor,
                "liquidity_score": score.liquidity_score,
                "leader_score": score.leader_score,
                "copy_degradation_bps": score.copy_degradation_bps,
                "edge_remaining_bps": score.edge_remaining_bps if score.edge_remaining_bps is not None else -9999.0,
                "opportunity_score": score.opportunity_score,
                "risk_score": score.risk_score,
                "price_deviation_bps": score.price_deviation_bps,
                "adverse_price_move_bps": score.adverse_price_move_bps,
                "simulated_notional_usdt": score.simulated_notional_usdt,
                "decision_reason": decision_reason,
                "shadow_outcome_bps": round(shadow_outcome_bps, 2),
            }

        for row in chronological:
            current_delta_key = delta_key(row)
            if current_delta_key in processed_keys:
                continue
            processed_keys.add(current_delta_key)
            action = copy_delta_action(row)
            direction = copy_delta_direction(row, action)
            event: dict[str, Any] = {
                "delta_key": current_delta_key,
                "wallet_address": row.wallet_address,
                "coin": row.coin,
                "leader_action": action,
                "leader_side": direction,
                "observed_at_ms": delta_event_time_ms(row),
                "leader_price": row.price,
                "leader_delta_size": row.delta_size,
                "leader_notional_usdc": row.delta_notional_usdc,
                "bot_replay_action": "NO_TRADE",
                "status": "REFUSED",
                "estimated_net_pnl_usdc": None,
                "bot_position_size_after": None,
                "reason": None,
                "research_only": True,
                "paper_mode": "PAPER_LOCAL_USDT_ONLY",
            }
            if action == "UNKNOWN" or direction is None:
                event["reason"] = "UNKNOWN_DELTA"
                ledger_events.append(event)
                continue
            if row.price is None or row.price <= 0:
                event["reason"] = "PRICE_MISSING"
                ledger_events.append(event)
                continue

            key = (row.wallet_address.lower(), row.coin.upper(), direction)
            metrics = opportunity_metrics(row, direction)
            event.update(metrics)

            if action in {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}:
                if is_data_stale:
                    event["reason"] = f"REJECT_STALE_DATA:{','.join(stale_sources)}"
                    ledger_events.append(event)
                    continue

                if metrics["decision_reason"] != "EDGE_OK_FOR_LOCAL_SIMULATION":
                    event["reason"] = str(metrics["decision_reason"])
                    ledger_events.append(event)
                    continue

                desired_notional = float(metrics.get("simulated_notional_usdt") or 0.0)
                if desired_notional <= 0:
                    event["reason"] = "MAX_EXPOSURE_REACHED"
                    ledger_events.append(event)
                    continue

                size = desired_notional / float(row.price)
                notional = desired_notional
                cost = notional * self.cost_bps / 10_000.0
                previous = positions.get(key, {"size": 0.0, "avg_price": 0.0, "entry_costs": 0.0})

                if action in {"ADD", "INCREASE"} and previous["size"] <= 0:
                    if len(positions) >= max_open_positions:
                        event["reason"] = "MAX_VIRTUAL_POSITIONS_REACHED"
                        ledger_events.append(event)
                        continue
                    event["bot_replay_action"] = "PAPER_JOIN_ADD_AS_ENTRY"
                    event["reason"] = "JOINED_LEADER_ADD_WITH_SMALL_CAPPED_POSITION"
                elif len(positions) >= max_open_positions and previous["size"] <= 0:
                    event["reason"] = "MAX_VIRTUAL_POSITIONS_REACHED"
                    ledger_events.append(event)
                    continue

                new_size = previous["size"] + size
                avg_price = (
                    ((previous["avg_price"] * previous["size"]) + (float(row.price) * size)) / new_size
                    if new_size > 0
                    else float(row.price)
                )
                positions[key] = {
                    "size": new_size,
                    "avg_price": avg_price,
                    "entry_costs": previous["entry_costs"] + cost,
                }
                replay_action = "PAPER_ENTRY_REPLAYED" if action.startswith("OPEN") else "PAPER_ADD_REPLAYED"
                if event["bot_replay_action"] == "PAPER_JOIN_ADD_AS_ENTRY":
                    replay_action = "PAPER_JOIN_ADD_AS_ENTRY"

                event.update(
                    {
                        "bot_replay_action": replay_action,
                        "status": "LOCAL_REPLAY",
                        "estimated_net_pnl_usdc": round(-cost, 6),
                        "fee_cost_usdc": round(cost, 6),
                        "bot_position_size_after": round(new_size, 10),
                        "copied_notional_usdt": round(notional, 6),
                        "reason": event.get("reason") or "LOCAL_REPLAY_ONLY_EDGE_GATE_REQUIRED_FOR_REAL_PAPER_INTENT",
                    }
                )
                ledger_events.append(event)
                continue

            if action in {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT"}:
                previous = positions.get(key)
                if previous is None or previous["size"] <= 0:
                    event["reason"] = "NO_MATCHING_PAPER_POSITION_FOR_CLOSE"
                    ledger_events.append(event)
                    continue

                size = abs(float(row.delta_size or row.fill_size or previous["size"]))
                close_size = previous["size"] if action.startswith("CLOSE") or size <= 0 else min(previous["size"], size)
                if direction == "LONG":
                    gross_pnl = (float(row.price) - previous["avg_price"]) * close_size
                else:
                    gross_pnl = (previous["avg_price"] - float(row.price)) * close_size

                exit_cost = close_size * float(row.price) * self.cost_bps / 10_000.0
                allocated_entry_cost = previous["entry_costs"] * (close_size / previous["size"])
                net_pnl = gross_pnl - exit_cost
                remaining_size = max(0.0, previous["size"] - close_size)

                if remaining_size <= 1e-12:
                    positions.pop(key, None)
                else:
                    positions[key] = {
                        "size": remaining_size,
                        "avg_price": previous["avg_price"],
                        "entry_costs": previous["entry_costs"] - allocated_entry_cost,
                    }

                event.update(
                    {
                        "bot_replay_action": "PAPER_CLOSE_REPLAYED" if action.startswith("CLOSE") else "PAPER_REDUCE_REPLAYED",
                        "status": "LOCAL_REPLAY",
                        "estimated_net_pnl_usdc": round(net_pnl, 6),
                        "gross_pnl_usdc": round(gross_pnl, 6),
                        "fee_cost_usdc": round(exit_cost, 6),
                        "bot_position_size_after": round(remaining_size, 10),
                        "copied_notional_usdt": round(close_size * float(row.price), 6),
                        "reason": "LOCAL_REPLAY_ONLY_NOT_AN_ORDER",
                    }
                )
                ledger_events.append(event)
                continue

            event["reason"] = "UNSUPPORTED_DELTA_FOR_REPLAY"
            ledger_events.append(event)

        mid_prices = mid_prices or {}
        open_positions: list[dict[str, Any]] = []
        unrealized_pnl = 0.0
        persisted_positions: dict[str, dict[str, Any]] = {}
        for (wallet, coin, direction), position in positions.items():
            mark_price = mid_prices.get(coin)
            if mark_price is None:
                mark_price = position["avg_price"]
            if direction == "LONG":
                gross_unrealized = (mark_price - position["avg_price"]) * position["size"]
            else:
                gross_unrealized = (position["avg_price"] - mark_price) * position["size"]

            exit_cost_estimate = abs(position["size"] * mark_price) * self.cost_bps / 10_000.0
            net_unrealized = gross_unrealized - exit_cost_estimate
            unrealized_pnl += net_unrealized

            open_positions.append(
                {
                    "wallet_address": wallet,
                    "coin": coin,
                    "direction": direction,
                    "size": round(position["size"], 10),
                    "avg_entry_price": round(position["avg_price"], 8),
                    "mark_price": round(mark_price, 8),
                    "entry_costs_remaining": round(position["entry_costs"], 6),
                    "unrealized_pnl_usdc": round(net_unrealized, 6),
                    "research_only": True,
                }
            )
            persisted_positions[encode_position_key(wallet, coin, direction)] = {
                "wallet_address": wallet,
                "coin": coin,
                "direction": direction,
                "size": round(float(position["size"]), 12),
                "avg_price": round(float(position["avg_price"]), 12),
                "entry_costs": round(float(position["entry_costs"]), 12),
            }

        open_positions.sort(key=lambda item: abs(float(item["unrealized_pnl_usdc"])), reverse=True)
        ledger_events = ledger_events[-max_events:]

        realized_net_pnl = sum(
            float(row.get("estimated_net_pnl_usdc") or 0.0)
            for row in ledger_events
            if row.get("status") == "LOCAL_REPLAY"
        )

        entry_costs_paid = sum(
            float(row.get("fee_cost_usdc") or 0.0)
            for row in ledger_events
            if row.get("bot_replay_action") in {"PAPER_ENTRY_REPLAYED", "PAPER_ADD_REPLAYED", "PAPER_JOIN_ADD_AS_ENTRY"}
        )
        exit_costs_paid = sum(
            float(row.get("fee_cost_usdc") or 0.0)
            for row in ledger_events
            if row.get("bot_replay_action") in {"PAPER_CLOSE_REPLAYED", "PAPER_REDUCE_REPLAYED"}
        )
        reproduced_entries = sum(
            1
            for row in ledger_events
            if row.get("bot_replay_action") in {"PAPER_ENTRY_REPLAYED", "PAPER_ADD_REPLAYED", "PAPER_JOIN_ADD_AS_ENTRY"}
        )
        reproduced_exits = sum(
            1
            for row in ledger_events
            if row.get("bot_replay_action") in {"PAPER_CLOSE_REPLAYED", "PAPER_REDUCE_REPLAYED"}
        )
        refused = sum(1 for row in ledger_events if row.get("status") == "REFUSED")
        total_pnl = realized_net_pnl + unrealized_pnl

        # Advanced Analytics
        running_pnl = 0.0
        max_equity = 0.0
        max_drawdown = 0.0
        pos_pnl_sum = 0.0
        neg_pnl_sum = 0.0
        shadow_lost_bps = 0.0
        wins = 0
        losses = 0

        for e in ledger_events:
            val = float(e.get("estimated_net_pnl_usdc") or 0.0)
            if val > 0:
                pos_pnl_sum += val
                wins += 1
            elif val < 0:
                neg_pnl_sum += abs(val)
                losses += 1

            running_pnl += val
            max_equity = max(max_equity, running_pnl)
            drawdown = max_equity - running_pnl
            max_drawdown = max(max_drawdown, drawdown)

            if e.get("status") == "REFUSED":
                shadow_lost_bps += float(e.get("shadow_outcome_bps") or 0.0)

        profit_factor = pos_pnl_sum / neg_pnl_sum if neg_pnl_sum > 0 else 1.0
        win_rate = (wins / (wins + losses) * 100.0) if (wins + losses) > 0 else 0.0
        avg_trade = (realized_net_pnl / (reproduced_entries + reproduced_exits)) if (reproduced_entries + reproduced_exits) > 0 else 0.0
        global_health = self.calculate_global_health_score(health_map)

        return {
            "events": list(reversed(ledger_events[-240:])),
            "ledger_events": ledger_events,
            "processed_delta_keys": sorted(processed_keys)[-10_000:],
            "virtual_positions_state": persisted_positions,
            "reproduced_entries": reproduced_entries,
            "reproduced_exits": reproduced_exits,
            "refused": refused,
            "open_local_positions": len(positions),
            "open_positions": open_positions[:25],
            "realized_net_pnl_usdc": round(realized_net_pnl, 6),
            "unrealized_pnl_usdc": round(unrealized_pnl, 6),
            "estimated_net_pnl_usdc": round(total_pnl, 6),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_usdc": round(max_drawdown, 2),
            "win_rate": round(win_rate, 1),
            "avg_trade_net_usdc": round(avg_trade, 4),
            "entry_costs_paid_usdc": round(entry_costs_paid, 6),
            "exit_costs_paid_usdc": round(exit_costs_paid, 6),
            "total_costs_paid_usdc": round(entry_costs_paid + exit_costs_paid, 6),
            "shadow_lost_bps": round(shadow_lost_bps, 2),
            "global_health_score": global_health,
            "cost_model_bps": self.cost_bps,
            "is_data_stale": is_data_stale,
            "stale_sources": stale_sources,
            "magic_profile": {
                "mode": "fresh_leader_following_simulation",
                "starting_equity_usdt": starting_equity_usdt,
                "max_position_notional_usdt": max_position_notional_usdt,
                "max_open_positions": max_open_positions,
                "min_edge_required_bps": self.min_edge_required_bps,
                "max_signal_age_seconds": int(self.max_signal_age_ms / 1000),
                "consensus_window_seconds": int(self.consensus_window_ms / 1000),
                "holding_policy": "hold_until_matching_leader_reduce_or_close",
                "red_pnl_exit_policy": "never_exit_only_because_unrealized_pnl_is_negative",
                "execution": "forbidden",
            },
        }
