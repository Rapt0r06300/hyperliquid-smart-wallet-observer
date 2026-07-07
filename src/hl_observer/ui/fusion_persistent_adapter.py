"""Persist accepted fusion paper orders into the live simulation state.

The fusion runtime can decide that a paper-only strategy would open a position.
This adapter is the missing bridge to the UI simulation for orders that have
passed the local canonical PaperEngine. It also records one local ledger
heartbeat per external profile execution, so the simulation can prove that each
installed GitHub-derived paper adapter ran independently even when it did not
open a position. External GitHub profile orders are shadow-only by default: they
may be used as evidence, diagnostics, and A/B replay candidates, but they must
not write positions directly unless an explicit local research flag is enabled.
It never sends an order or touches external money.
"""

from __future__ import annotations

import os
from typing import Any

from hl_observer.simulation.session_memory import evaluate_coin_side_session_memory
from hl_observer.ui.state import UiState

MATERIALIZABLE_STRATEGY_PREFIXES = ("ext_", "copy_")
COPY_LIKE_FAMILY_TOKENS = ("copy", "whale", "mirror", "autonomous_sltp", "direction_hunt")
EXTERNAL_DIRECT_MATERIALIZATION_ENV = "HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION"
AB_RESEARCH_ACK_ENV = "HYPERSMART_AB_RESEARCH_ACK"
_ENABLED_VALUES = {"1", "true", "yes", "on"}


def _env_enabled(name: str) -> bool:
    return str(os.getenv(name, "0")).strip().lower() in _ENABLED_VALUES


def _external_direct_materialization_enabled() -> bool:
    """Double verrou: la matérialisation directe des profils GitHub exige les
    DEUX flags. Un seul flag ne suffit plus — cela évite qu'un ancien launcher
    ou une variable oubliée ne rebranche le bus direct par accident."""

    return _env_enabled(EXTERNAL_DIRECT_MATERIALIZATION_ENV) and _env_enabled(AB_RESEARCH_ACK_ENV)


def apply_fusion_paper_orders_to_state(
    state: UiState,
    fusion_status: dict[str, Any],
    *,
    current_ms: int,
) -> dict[str, Any]:
    """Apply newly accepted fusion paper orders to ``UiState``.

    Returns a small report suitable for diagnostics. The function is intentionally
    conservative: only OPEN paper trades emitted by the local fusion runtime are
    accepted, duplicates are skipped by ``source_delta_id``/``trade_id``, and all
    rows are tagged as local simulation only.
    """

    result = {
        "applied_count": 0,
        "skipped_count": 0,
        "reasons": [],
        "paper_only": True,
        "real_execution": False,
        "external_action": False,
        "external_direct_orders_shadowed": 0,
    }
    if not isinstance(fusion_status, dict) or fusion_status.get("status") != "OK_LIVE_FUSION_RUNTIME":
        result["reasons"].append("FUSION_NOT_READY")
        return result
    if fusion_status.get("real_execution") is not False or fusion_status.get("paper_only") is not True:
        result["reasons"].append("FUSION_SAFETY_FLAGS_INVALID")
        return result

    runtime = fusion_status.get("runtime")
    if not isinstance(runtime, dict):
        result["reasons"].append("MISSING_RUNTIME")
        return result
    if not isinstance(state.simulation_virtual_positions, dict):
        state.simulation_virtual_positions = {}
    if not isinstance(state.simulation_ledger_events, list):
        state.simulation_ledger_events = []
    if not isinstance(state.simulation_processed_delta_keys, set):
        state.simulation_processed_delta_keys = set(state.simulation_processed_delta_keys or [])

    _record_external_profile_executions(
        state,
        runtime=runtime,
        current_ms=current_ms,
        result=result,
    )

    paper_engine = fusion_status.get("paper_engine")
    if not isinstance(paper_engine, dict):
        paper_engine = runtime.get("paper_engine")
    engine_decisions = paper_engine.get("decisions") if isinstance(paper_engine, dict) else []
    accepted_decisions = [
        item
        for item in engine_decisions
        if isinstance(item, dict) and item.get("accepted") is True and isinstance(item.get("position"), dict)
    ]
    paper_orders = runtime.get("paper_orders")
    if not isinstance(paper_orders, list):
        paper_orders = []
    if not paper_orders and not accepted_decisions:
        result["reasons"].append("NO_PAPER_ORDERS")
        _trim_ledger(state)
        return result
    # Copy-follow orders are also emitted as direct profile orders by the
    # external GitHub simulation bus. They are useful as diagnostics, but they
    # are intentionally shadow-only by default. The product direction is now
    # "distill ideas into one measurable engine", not "let every cloned profile
    # write positions independently". The canonical PaperEngine remains the
    # normal writer. Direct materialization is available only for explicit local
    # A/B research with HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION=1.
    allow_direct_copy_fallback = not accepted_decisions
    shadow_direct_orders = [
        item
        for item in paper_orders
        if _is_materializable_direct_paper_order(item, allow_copy_conflict_resolver=allow_direct_copy_fallback)
    ]
    if _external_direct_materialization_enabled():
        direct_orders = shadow_direct_orders
    else:
        direct_orders = []
        if shadow_direct_orders:
            result["external_direct_orders_shadowed"] = len(shadow_direct_orders)
            result["skipped_count"] += len(shadow_direct_orders)
            result["reasons"].append("EXTERNAL_GITHUB_DIRECT_MATERIALIZATION_DISABLED")
            if _env_enabled(EXTERNAL_DIRECT_MATERIALIZATION_ENV) and not _env_enabled(AB_RESEARCH_ACK_ENV):
                result["reasons"].append("EXTERNAL_DIRECT_REQUIRES_AB_RESEARCH_ACK")
    if not accepted_decisions and not direct_orders:
        result["reasons"].append("NO_MATERIALIZABLE_PAPER_POSITION")
        _trim_ledger(state)
        return result

    for decision in accepted_decisions:
        trade = decision.get("trade")
        position = decision.get("position")
        if not isinstance(trade, dict) or not isinstance(position, dict):
            result["skipped_count"] += 1
            continue
        source_delta_id = str(position.get("source_delta_id") or trade.get("source_delta_id") or "")
        trade_id = str(trade.get("trade_id") or "")
        delta_key = f"fusion-runtime:{source_delta_id or trade_id}"
        if not source_delta_id and not trade_id:
            result["skipped_count"] += 1
            result["reasons"].append("MISSING_PAPER_REF")
            continue
        if delta_key in state.simulation_processed_delta_keys:
            result["skipped_count"] += 1
            result["reasons"].append("DUPLICATE_FUSION_PAPER_ORDER")
            continue

        coin = str(position.get("coin") or trade.get("coin") or "").upper()
        side = str(position.get("side") or trade.get("side") or "").upper()
        if coin == "" or side not in {"LONG", "SHORT"}:
            result["skipped_count"] += 1
            result["reasons"].append("INVALID_PAPER_POSITION_FIELDS")
            continue
        entry_price = _safe_float(position.get("entry_price")) or _safe_float(trade.get("fill_price")) or 0.0
        quantity = abs(_safe_float(position.get("quantity")) or 0.0)
        notional = abs(_safe_float(position.get("notional_usdt")) or _safe_float(trade.get("notional_usdt")) or 0.0)
        if entry_price <= 0 or quantity <= 0 or notional <= 0:
            result["skipped_count"] += 1
            result["reasons"].append("INVALID_PAPER_POSITION_NUMBERS")
            continue
        capped = _cap_paper_notional_and_quantity(notional, quantity, entry_price)
        notional = capped["notional"]
        quantity = capped["quantity"]

        wallet = str(position.get("leader_wallet") or "")
        min_notional_refusal = _min_paper_notional_refusal(notional)
        if min_notional_refusal:
            result["skipped_count"] += 1
            result["reasons"].append(min_notional_refusal)
            _record_portfolio_order_refusal(
                state,
                delta_key=delta_key,
                current_ms=current_ms,
                reason=min_notional_refusal,
                coin=coin,
                side=side,
                wallet=wallet,
                reference_price=entry_price,
                notional_usdt=notional,
                source="FUSION_RUNTIME_REJECTED_MIN_NOTIONAL",
                evidence_hash=str(decision.get("evidence_hash") or trade_id or delta_key),
            )
            state.simulation_processed_delta_keys.add(delta_key)
            continue
        position_key = f"{wallet or 'fusion'}|{coin}|{side}"
        if position_key in state.simulation_virtual_positions:
            result["skipped_count"] += 1
            result["reasons"].append("POSITION_ALREADY_OPEN")
            state.simulation_processed_delta_keys.add(delta_key)
            continue
        portfolio_refusal = _portfolio_open_refusal(state, new_notional_usdt=notional)
        if portfolio_refusal:
            result["skipped_count"] += 1
            result["reasons"].append(portfolio_refusal)
            _record_portfolio_order_refusal(
                state,
                delta_key=delta_key,
                current_ms=current_ms,
                reason=portfolio_refusal,
                coin=coin,
                side=side,
                wallet=wallet,
                reference_price=entry_price,
                notional_usdt=notional,
                source="FUSION_RUNTIME_REJECTED_PORTFOLIO_GUARD",
                evidence_hash=str(decision.get("evidence_hash") or trade_id or delta_key),
            )
            state.simulation_processed_delta_keys.add(delta_key)
            continue

        opened_at_ms = int(_safe_float(position.get("opened_at_ms")) or current_ms)
        entry_costs = notional * (_safe_float(trade.get("fees_and_cost_bps")) or 0.0) / 10_000.0
        state.simulation_virtual_positions[position_key] = {
            "wallet_address": wallet,
            "leader_wallet": wallet,
            "coin": coin,
            "direction": side,
            "side": side,
            "size": quantity if side == "LONG" else -quantity,
            "avg_price": entry_price,
            "entry_price": entry_price,
            "entry_costs": round(entry_costs, 8),
            "opened_at_ms": opened_at_ms,
            "last_update_at_ms": current_ms,
            "source_delta_key": delta_key,
            "position_mode": "EXTERNAL_GITHUB_FUSION_PAPER",
            "leader_wallets_csv": wallet,
            "last_replay_action": "FUSION_PAPER_ENTRY",
            "last_evidence_hash": str(decision.get("evidence_hash") or ""),
            "last_paper_ref": trade_id,
            "last_v9_decision": "FUSION_RUNTIME_ACCEPTED",
            "last_v9_evidence_hash": str(decision.get("evidence_hash") or ""),
            "entry_count": 1,
            "increase_count": 0,
            "reduce_count": 0,
            "paper_only": True,
            "read_only": True,
            "external_action": False,
            "notional_cap_applied": capped["cap_applied"],
        }
        state.simulation_ledger_events.append(
            {
                "delta_key": delta_key,
                "wallet_address": wallet,
                "coin": coin,
                "leader_action": "FUSION_RUNTIME_ENTRY",
                "leader_side": side,
                "leader_price": entry_price,
                "leader_notional_usdc": notional,
                "observed_at_ms": opened_at_ms,
                "bot_replay_action": "FUSION_PAPER_ENTRY",
                "paper_action_type": "OPEN",
                "status": "LOCAL_REPLAY",
                "estimated_net_pnl_usdc": None,
                "gross_pnl_usdc": None,
                "fee_cost_usdc": round(entry_costs, 8),
                "copied_notional_usdt": notional,
                "bot_position_size_after": quantity if side == "LONG" else -quantity,
                "entry_price": entry_price,
                "average_entry_price": entry_price,
                "reason": "EXTERNAL_GITHUB_FUSION_ACCEPTED_PAPER_ONLY",
                "evidence_hash": str(decision.get("evidence_hash") or ""),
                "paper_mode": "PAPER_LOCAL_USDT_ONLY",
                "research_only": True,
                "simulation_only": True,
                "read_only": True,
                "external_action": False,
                "real_execution": False,
                "execution": "forbidden",
                "venue_endpoint": None,
                "secret_material_used": False,
                "notional_cap_applied": capped["cap_applied"],
            }
        )
        state.simulation_processed_delta_keys.add(delta_key)
        state.simulation_reproduced_entries_total += 1
        state.simulation_entry_costs_paid_usdc += entry_costs
        result["applied_count"] += 1

    for order in direct_orders:
        if not isinstance(order, dict):
            continue
        order_id = str(order.get("order_id") or "")
        strategy_id = str(order.get("strategy_id") or "")
        delta_key = f"fusion-runtime-order:{order_id or strategy_id}"
        if not order_id:
            result["skipped_count"] += 1
            result["reasons"].append("MISSING_DIRECT_ORDER_REF")
            continue
        if delta_key in state.simulation_processed_delta_keys:
            result["skipped_count"] += 1
            result["reasons"].append("DUPLICATE_DIRECT_PAPER_ORDER")
            continue

        action = _paper_order_action(order)
        if action == "CLOSE":
            _apply_direct_paper_close_order(
                state,
                order,
                delta_key=delta_key,
                current_ms=current_ms,
                result=result,
            )
            continue
        if action != "OPEN":
            result["skipped_count"] += 1
            result["reasons"].append("UNSUPPORTED_DIRECT_PAPER_ACTION")
            continue
        quality_refusal = _direct_order_quality_refusal(order, state=state)
        if quality_refusal:
            result["skipped_count"] += 1
            result["reasons"].append(quality_refusal)
            _record_direct_order_refusal(
                state,
                order,
                delta_key=delta_key,
                current_ms=current_ms,
                reason=quality_refusal,
            )
            state.simulation_processed_delta_keys.add(delta_key)
            continue

        coin = str(order.get("coin") or "").upper()
        side = str(order.get("side") or "").upper()
        notional = abs(_safe_float(order.get("notional_usdt")) or 0.0)
        entry_price = _safe_float(order.get("reference_price")) or 0.0
        if coin == "" or side not in {"LONG", "SHORT"} or entry_price <= 0 or notional <= 0:
            result["skipped_count"] += 1
            result["reasons"].append("INVALID_DIRECT_PAPER_ORDER_FIELDS")
            continue
        capped = _cap_paper_notional_and_quantity(notional, notional / entry_price, entry_price)
        notional = capped["notional"]
        quantity = capped["quantity"]
        quantity = notional / entry_price
        min_notional_refusal = _min_paper_notional_refusal(notional)
        if min_notional_refusal:
            result["skipped_count"] += 1
            result["reasons"].append(min_notional_refusal)
            _record_direct_order_refusal(
                state,
                order,
                delta_key=delta_key,
                current_ms=current_ms,
                reason=min_notional_refusal,
            )
            state.simulation_processed_delta_keys.add(delta_key)
            continue
        position_key = f"{strategy_id or 'external_arbitrage'}|{coin}|{side}"
        if position_key in state.simulation_virtual_positions:
            result["skipped_count"] += 1
            result["reasons"].append("DIRECT_POSITION_ALREADY_OPEN")
            state.simulation_processed_delta_keys.add(delta_key)
            continue
        portfolio_refusal = _portfolio_open_refusal(state, new_notional_usdt=notional)
        if portfolio_refusal:
            result["skipped_count"] += 1
            result["reasons"].append(portfolio_refusal)
            _record_portfolio_order_refusal(
                state,
                delta_key=delta_key,
                current_ms=current_ms,
                reason=portfolio_refusal,
                coin=coin,
                side=side,
                wallet=strategy_id,
                reference_price=entry_price,
                notional_usdt=notional,
                source="FUSION_DIRECT_RUNTIME_REJECTED_PORTFOLIO_GUARD",
                evidence_hash=str(order.get("order_id") or delta_key),
                strategy_id=strategy_id,
                metadata=order.get("metadata") if isinstance(order.get("metadata"), dict) else {},
            )
            state.simulation_processed_delta_keys.add(delta_key)
            continue

        fees_bps = _safe_float((order.get("metadata") or {}).get("fees_bps") if isinstance(order.get("metadata"), dict) else None)
        entry_costs = notional * (fees_bps if fees_bps is not None else 8.0) / 10_000.0
        metadata = order.get("metadata") if isinstance(order.get("metadata"), dict) else {}
        evidence_fields = _copy_direct_evidence_fields(metadata)
        state.simulation_virtual_positions[position_key] = {
            "wallet_address": strategy_id,
            "leader_wallet": strategy_id,
            "coin": coin,
            "direction": side,
            "side": side,
            "size": quantity if side == "LONG" else -quantity,
            "avg_price": entry_price,
            "entry_price": entry_price,
            "entry_costs": round(entry_costs, 8),
            "opened_at_ms": current_ms,
            "last_update_at_ms": current_ms,
            "source_delta_key": delta_key,
            "position_mode": _position_mode_for_direct_order(order),
            "leader_wallets_csv": strategy_id,
            "last_replay_action": "FUSION_DIRECT_PAPER_ENTRY",
            "last_evidence_hash": str(order_id),
            "last_paper_ref": order_id,
            "last_v9_decision": "FUSION_DIRECT_RUNTIME_ACCEPTED",
            "last_v9_evidence_hash": str(order_id),
            "entry_count": 1,
            "increase_count": 0,
            "reduce_count": 0,
            "strategy_id": strategy_id,
            "strategy_family": str(metadata.get("profile_family") or "external_arbitrage"),
            "source_a": metadata.get("source_a"),
            "source_b": metadata.get("source_b"),
            "spread_bps": metadata.get("spread_bps"),
            **evidence_fields,
            "paper_only": True,
            "read_only": True,
            "external_action": False,
            "notional_cap_applied": capped["cap_applied"],
        }
        state.simulation_ledger_events.append(
            {
                "delta_key": delta_key,
                "wallet_address": strategy_id,
                "coin": coin,
                "leader_action": "FUSION_DIRECT_RUNTIME_ENTRY",
                "leader_side": side,
                "leader_price": entry_price,
                "leader_notional_usdc": notional,
                "observed_at_ms": current_ms,
                "bot_replay_action": "FUSION_DIRECT_PAPER_ENTRY",
                "paper_action_type": "OPEN",
                "status": "LOCAL_REPLAY",
                "estimated_net_pnl_usdc": None,
                "gross_pnl_usdc": None,
                "fee_cost_usdc": round(entry_costs, 8),
                "copied_notional_usdt": notional,
                "bot_position_size_after": quantity if side == "LONG" else -quantity,
                "entry_price": entry_price,
                "average_entry_price": entry_price,
                "reason": _ledger_reason_for_direct_order(order),
                "evidence_hash": str(order_id),
                "paper_mode": "PAPER_LOCAL_USDT_ONLY",
                "strategy_id": strategy_id,
                "strategy_family": str(metadata.get("profile_family") or "external_arbitrage"),
                "source_a": metadata.get("source_a"),
                "source_b": metadata.get("source_b"),
                "spread_bps": metadata.get("spread_bps"),
                **evidence_fields,
                "research_only": True,
                "simulation_only": True,
                "read_only": True,
                "external_action": False,
                "real_execution": False,
                "execution": "forbidden",
                "venue_endpoint": None,
                "secret_material_used": False,
                "notional_cap_applied": capped["cap_applied"],
            }
        )
        state.simulation_processed_delta_keys.add(delta_key)
        state.simulation_reproduced_entries_total += 1
        state.simulation_entry_costs_paid_usdc += entry_costs
        result["applied_count"] += 1

    _trim_ledger(state)
    if not result["reasons"]:
        result["reasons"].append("OK")
    return result


def _is_materializable_direct_paper_order(
    value: object,
    *,
    allow_copy_conflict_resolver: bool = False,
) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("accepted") is not True:
        return False
    if value.get("paper_only") is not True or value.get("real_execution") is not False:
        return False
    strategy_id = str(value.get("strategy_id") or "")
    action = _paper_order_action(value)
    if action == "CLOSE":
        return strategy_id.startswith(MATERIALIZABLE_STRATEGY_PREFIXES)
    if not strategy_id.startswith(MATERIALIZABLE_STRATEGY_PREFIXES):
        return False
    metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
    if str(metadata.get("source") or "") == "copy_conflict_resolver" and not allow_copy_conflict_resolver:
        # Copy-follow entries pass through the existing PaperEngine path when it
        # accepts the signal. The direct connector order is then kept for audit,
        # not for a second open.
        return False
    side = str(value.get("side") or "").upper()
    if side not in {"LONG", "SHORT"}:
        return False
    notional = _safe_float(value.get("notional_usdt")) or 0.0
    return (_safe_float(value.get("reference_price")) or 0.0) > 0 and notional > 0


def _record_external_profile_executions(
    state: UiState,
    *,
    runtime: dict[str, Any],
    current_ms: int,
    result: dict[str, Any],
) -> None:
    executions = runtime.get("external_profile_executions")
    if not isinstance(executions, list):
        result["external_profiles_executed"] = 0
        result["external_profile_events_recorded"] = 0
        return
    session = runtime.get("session") if isinstance(runtime.get("session"), dict) else {}
    session_id = str(session.get("session_id") or f"fusion-{current_ms}")
    executed_count = 0
    recorded_count = 0
    skipped_count = 0
    for item in executions:
        if not isinstance(item, dict):
            continue
        profile_id = str(item.get("profile_id") or "")
        if not profile_id:
            continue
        if item.get("installed") is not True or str(item.get("status") or "") != "EXECUTED":
            continue
        executed_count += 1
        delta_key = f"fusion-engine-exec:{session_id}:{profile_id}"
        if delta_key in state.simulation_processed_delta_keys:
            skipped_count += 1
            continue
        state.simulation_ledger_events.append(
            {
                "delta_key": delta_key,
                "wallet_address": profile_id,
                "coin": str(item.get("family") or item.get("kind") or "EXTERNAL").upper(),
                "leader_action": "EXTERNAL_ENGINE_EVALUATED",
                "leader_side": "NONE",
                "leader_price": None,
                "leader_notional_usdc": 0.0,
                "observed_at_ms": current_ms,
                "bot_replay_action": "EXTERNAL_GITHUB_PROFILE_EVALUATED",
                "paper_action_type": "ENGINE_EVALUATION",
                "status": "SIMULATION_ENGINE_EVENT",
                "estimated_net_pnl_usdc": None,
                "gross_pnl_usdc": None,
                "fee_cost_usdc": 0.0,
                "copied_notional_usdt": 0.0,
                "bot_position_size_after": None,
                "reason": str(item.get("reason") or item.get("decision") or "PROFILE_EVALUATED"),
                "decision": str(item.get("decision") or ""),
                "candidate_count": int(_safe_float(item.get("candidate_count")) or 0),
                "accepted_paper_orders": int(_safe_float(item.get("accepted_paper_orders")) or 0),
                "profile_id": profile_id,
                "repo_id": str(item.get("repo_id") or ""),
                "profile_family": str(item.get("family") or ""),
                "profile_kind": str(item.get("kind") or ""),
                "paper_mode": "PAPER_LOCAL_USDT_ONLY",
                "research_only": True,
                "simulation_only": True,
                "read_only": True,
                "external_action": False,
                "real_execution": False,
                "execution": "forbidden",
                "venue_endpoint": None,
                "secret_material_used": False,
            }
        )
        state.simulation_processed_delta_keys.add(delta_key)
        recorded_count += 1
    result["external_profiles_executed"] = executed_count
    result["external_profile_events_recorded"] = recorded_count
    result["external_profile_events_skipped"] = skipped_count


def _record_direct_order_refusal(
    state: UiState,
    order: dict[str, Any],
    *,
    delta_key: str,
    current_ms: int,
    reason: str,
) -> None:
    metadata = order.get("metadata") if isinstance(order.get("metadata"), dict) else {}
    strategy_id = str(order.get("strategy_id") or "")
    coin = str(order.get("coin") or "").upper()
    side = str(order.get("side") or "").upper()
    reference_price = _safe_float(order.get("reference_price"))
    notional = abs(_safe_float(order.get("notional_usdt")) or 0.0)
    state.simulation_ledger_events.append(
        {
            "delta_key": delta_key,
            "wallet_address": strategy_id,
            "coin": coin,
            "leader_action": "FUSION_DIRECT_RUNTIME_REJECTED",
            "leader_side": side,
            "leader_price": reference_price,
            "leader_notional_usdc": notional,
            "observed_at_ms": current_ms,
            "bot_replay_action": "NO_TRADE",
            "paper_action_type": "NO_TRADE",
            "status": "REJECT_NO_TRADE",
            "estimated_net_pnl_usdc": None,
            "gross_pnl_usdc": None,
            "fee_cost_usdc": 0.0,
            "copied_notional_usdt": 0.0,
            "bot_position_size_after": None,
            "reason": reason,
            "evidence_hash": str(order.get("order_id") or delta_key),
            "paper_mode": "PAPER_LOCAL_USDT_ONLY",
            "strategy_id": strategy_id,
            "strategy_family": str(metadata.get("profile_family") or "external_profile"),
            "source_a": metadata.get("source_a"),
            "source_b": metadata.get("source_b"),
            "spread_bps": metadata.get("spread_bps"),
            **_copy_direct_evidence_fields(metadata),
            "research_only": True,
            "simulation_only": True,
            "read_only": True,
            "external_action": False,
            "real_execution": False,
            "execution": "forbidden",
            "venue_endpoint": None,
            "secret_material_used": False,
        }
    )


def _record_portfolio_order_refusal(
    state: UiState,
    *,
    delta_key: str,
    current_ms: int,
    reason: str,
    coin: str,
    side: str,
    wallet: str,
    reference_price: float,
    notional_usdt: float,
    source: str,
    evidence_hash: str,
    strategy_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    metadata = metadata if isinstance(metadata, dict) else {}
    state.simulation_ledger_events.append(
        {
            "delta_key": delta_key,
            "wallet_address": wallet,
            "coin": coin,
            "leader_action": source,
            "leader_side": side,
            "leader_price": reference_price,
            "leader_notional_usdc": abs(float(notional_usdt or 0.0)),
            "observed_at_ms": current_ms,
            "bot_replay_action": "NO_TRADE",
            "paper_action_type": "NO_TRADE",
            "status": "REJECT_NO_TRADE",
            "estimated_net_pnl_usdc": None,
            "gross_pnl_usdc": None,
            "fee_cost_usdc": 0.0,
            "copied_notional_usdt": 0.0,
            "bot_position_size_after": None,
            "reason": reason,
            "evidence_hash": evidence_hash,
            "paper_mode": "PAPER_LOCAL_USDT_ONLY",
            "strategy_id": strategy_id,
            "strategy_family": str(metadata.get("profile_family") or ""),
            **_copy_direct_evidence_fields(metadata),
            "research_only": True,
            "simulation_only": True,
            "read_only": True,
            "external_action": False,
            "real_execution": False,
            "execution": "forbidden",
            "venue_endpoint": None,
            "secret_material_used": False,
        }
    )


def _min_paper_notional_refusal(notional_usdt: float) -> str:
    """Plancher notional paper (replay A/B 2026-07-07).

    Justification mesurée sur logs frais: les micro-trades ont un brut positif
    mais un net négatif (fee drag ~59%). Le replay causal `notional_at_least_40`
    donne train ET validation positifs vs -1.77 USDC pour tous les trades.
    Désactivé par défaut (0); activé via HYPERSMART_MIN_PAPER_NOTIONAL_USDT.
    """

    minimum = _env_float("HYPERSMART_MIN_PAPER_NOTIONAL_USDT", 0.0)
    if minimum > 0 and abs(float(notional_usdt or 0.0)) < minimum:
        return "PAPER_NOTIONAL_BELOW_MINIMUM"
    return ""


def _portfolio_open_refusal(state: UiState, *, new_notional_usdt: float) -> str:
    """Global portfolio guard applied after strategy-level gates.

    Individual engines can each be reasonable and still collectively overfill the
    local wallet. This guard uses the live UiState positions as the source of
    truth so the simulation cannot open more exposure than the session budget.
    """

    positions = getattr(state, "simulation_virtual_positions", {}) or {}
    if not isinstance(positions, dict):
        return ""
    max_positions = _env_int("HYPERSMART_MAX_OPEN_POSITIONS", 12)
    if max_positions > 0 and len(positions) >= max_positions:
        return "PORTFOLIO_MAX_OPEN_POSITIONS"
    max_exposure = abs(_env_float("HYPERSMART_MAX_TOTAL_EXPOSURE_USDT", 400.0))
    current_exposure = _current_open_exposure_usdt(positions)
    if max_exposure > 0 and current_exposure + abs(float(new_notional_usdt or 0.0)) > max_exposure:
        return "PORTFOLIO_MAX_TOTAL_EXPOSURE"
    return ""


def _current_open_exposure_usdt(positions: dict[Any, Any]) -> float:
    exposure = 0.0
    for position in positions.values():
        if not isinstance(position, dict):
            continue
        notional = _safe_float(position.get("notional_usdt") or position.get("copied_notional_usdt"))
        if notional is None or notional <= 0:
            size = abs(_safe_float(position.get("size")) or 0.0)
            price = (
                _safe_float(position.get("avg_price"))
                or _safe_float(position.get("entry_price"))
                or _safe_float(position.get("mark_price"))
                or 0.0
            )
            notional = size * price
        exposure += abs(float(notional or 0.0))
    return exposure


def _direct_order_quality_refusal(value: dict[str, Any], *, state: UiState | None = None) -> str:
    """Gate external-profile paper orders before they touch the portfolio."""

    metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
    family = str(metadata.get("profile_family") or "").lower()
    if family == "cross_exchange_arbitrage":
        source_a = str(metadata.get("source_a") or "").strip().lower()
        source_b = str(metadata.get("source_b") or "").strip().lower()
        spread_bps = _safe_float(metadata.get("spread_bps"))
        min_spread_bps = _env_float("HYPERSMART_DIRECT_ARBITRAGE_MIN_SPREAD_BPS", 30.0)
        if not source_a or not source_b or source_a == source_b:
            return "DIRECT_ARBITRAGE_REQUIRES_DISTINCT_SOURCES"
        if spread_bps is None or spread_bps < min_spread_bps:
            return "DIRECT_ARBITRAGE_SPREAD_TOO_SMALL"
    if _is_copy_like_direct_family(family, strategy_id=str(value.get("strategy_id") or "")):
        return _copy_like_direct_order_refusal(value, state=state)
    return ""


def _copy_like_direct_order_refusal(value: dict[str, Any], *, state: UiState | None = None) -> str:
    metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
    coin = str(value.get("coin") or "").upper()
    side = str(value.get("side") or "").upper()
    if coin == "" or side not in {"LONG", "SHORT"}:
        return "DIRECT_COPY_INVALID_COIN_SIDE"

    max_positions = _env_int("HYPERSMART_DIRECT_COPY_MAX_OPEN_POSITIONS", 3)
    if state is not None and _open_quality_gated_positions_count(state) >= max_positions:
        return "DIRECT_COPY_MAX_OPEN_POSITIONS"

    consensus = _metadata_int(metadata, "leader_wallets_count", "consensus_wallets", "wallet_count", default=0)
    min_consensus = _env_int("HYPERSMART_DIRECT_COPY_MIN_CONSENSUS_WALLETS", 3)
    edge = _metadata_float(metadata, "edge_remaining_bps", "net_edge_bps")
    min_edge = _env_float("HYPERSMART_DIRECT_COPY_MIN_EDGE_BPS", 32.0)
    session_pnl = _current_session_pnl_usdc(state)
    if session_pnl <= -abs(_env_float("HYPERSMART_SESSION_LOSS_GUARD_USDC", 0.75)):
        min_edge += abs(_env_float("HYPERSMART_SESSION_LOSS_EDGE_BONUS_BPS", 20.0))
    if edge is None:
        return "DIRECT_COPY_EDGE_MISSING"
    if edge < min_edge:
        return "DIRECT_COPY_EDGE_TOO_SMALL"
    if consensus < min_consensus:
        strong_single_edge = min_edge + abs(_env_float("HYPERSMART_DIRECT_COPY_SINGLE_WALLET_EDGE_BONUS_BPS", 45.0))
        if edge < strong_single_edge:
            return "DIRECT_COPY_REQUIRES_CONSENSUS_OR_STRONG_EDGE"

    age_ms = _metadata_float(metadata, "signal_age_ms", "age_ms")
    max_age_ms = _env_float("HYPERSMART_DIRECT_COPY_MAX_SIGNAL_AGE_MS", 8_000.0)
    if age_ms is None:
        return "DIRECT_COPY_SIGNAL_AGE_MISSING"
    if age_ms > max_age_ms:
        return "DIRECT_COPY_SIGNAL_TOO_OLD"

    liquidity = _metadata_float(metadata, "liquidity_score")
    min_liquidity = _env_float("HYPERSMART_DIRECT_COPY_MIN_LIQUIDITY", 0.45)
    if liquidity is None:
        return "DIRECT_COPY_LIQUIDITY_MISSING"
    if liquidity < min_liquidity:
        return "DIRECT_COPY_LIQUIDITY_TOO_LOW"

    degradation = _metadata_float(metadata, "copy_degradation_bps")
    max_degradation = _env_float("HYPERSMART_DIRECT_COPY_MAX_DEGRADATION_BPS", 24.0)
    if degradation is not None and degradation > max_degradation:
        return "DIRECT_COPY_DEGRADATION_TOO_HIGH"

    if state is not None:
        memory = evaluate_coin_side_session_memory(
            events=getattr(state, "simulation_ledger_events", []) or [],
            coin=coin,
            side=side,
            edge_remaining_bps=float(edge),
            min_edge_required_bps=float(min_edge),
            consensus_wallets=int(consensus),
            liquidity_score=float(liquidity),
            starting_equity_usdt=float(getattr(state, "simulation_starting_equity_usdt", 1000.0) or 1000.0),
            extra_edge_after_loss_bps=abs(_env_float("HYPERSMART_DIRECT_COPY_RECOVERY_EDGE_BONUS_BPS", 24.0)),
            min_consensus_after_loss=max(min_consensus, _env_int("HYPERSMART_DIRECT_COPY_RECOVERY_MIN_CONSENSUS", 4)),
            min_liquidity_after_loss=max(min_liquidity, _env_float("HYPERSMART_DIRECT_COPY_RECOVERY_MIN_LIQUIDITY", 0.60)),
        )
        if not memory.allow_entry:
            return memory.reason
    return ""


def _position_mode_for_direct_order(value: dict[str, Any]) -> str:
    metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
    family = str(metadata.get("profile_family") or "").lower()
    if family == "cross_exchange_arbitrage":
        return "EXTERNAL_GITHUB_ARBITRAGE_PAPER"
    if "funding" in family:
        return "EXTERNAL_GITHUB_FUNDING_PAPER"
    if "copy" in family or "whale" in family:
        return "EXTERNAL_GITHUB_COPY_PAPER"
    if "triangular" in family:
        return "EXTERNAL_GITHUB_TRIANGULAR_PAPER"
    return "EXTERNAL_GITHUB_DIRECT_PAPER"


def _ledger_reason_for_direct_order(value: dict[str, Any]) -> str:
    mode = _position_mode_for_direct_order(value)
    if mode == "EXTERNAL_GITHUB_ARBITRAGE_PAPER":
        return "EXTERNAL_GITHUB_ARBITRAGE_ACCEPTED_PAPER_ONLY"
    if mode == "EXTERNAL_GITHUB_FUNDING_PAPER":
        return "EXTERNAL_GITHUB_FUNDING_ACCEPTED_PAPER_ONLY"
    if mode == "EXTERNAL_GITHUB_COPY_PAPER":
        return "EXTERNAL_GITHUB_COPY_ACCEPTED_PAPER_ONLY"
    if mode == "EXTERNAL_GITHUB_TRIANGULAR_PAPER":
        return "EXTERNAL_GITHUB_TRIANGULAR_ACCEPTED_PAPER_ONLY"
    return "EXTERNAL_GITHUB_PROFILE_ACCEPTED_PAPER_ONLY"


def _cap_paper_notional_and_quantity(notional: float, quantity: float, entry_price: float) -> dict[str, Any]:
    cap = abs(_env_float("HYPERSMART_MAX_POSITION_USDT", 40.0))
    clean_notional = max(0.0, float(notional or 0.0))
    clean_quantity = abs(float(quantity or 0.0))
    if cap <= 0 or entry_price <= 0 or clean_notional <= cap:
        return {"notional": clean_notional, "quantity": clean_quantity, "cap_applied": False}
    capped_quantity = cap / float(entry_price)
    return {"notional": round(cap, 8), "quantity": round(capped_quantity, 12), "cap_applied": True}


def _paper_order_action(value: object) -> str:
    if not isinstance(value, dict):
        return "OPEN"
    metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
    return str(value.get("action") or metadata.get("action") or "OPEN").upper()


def _copy_direct_evidence_fields(metadata: dict[str, Any]) -> dict[str, Any]:
    """Normalize measurable proof fields carried by copy-like GitHub profiles."""

    edge = metadata.get("edge_remaining_bps")
    if edge is None:
        edge = metadata.get("net_edge_bps")
    leader_wallets = metadata.get("leader_wallets_count")
    if leader_wallets is None:
        leader_wallets = metadata.get("consensus_wallets")
    return {
        "edge_remaining_bps": edge,
        "signal_age_ms": metadata.get("signal_age_ms") if metadata.get("signal_age_ms") is not None else metadata.get("age_ms"),
        "leader_wallets_count": leader_wallets,
        "liquidity_score": metadata.get("liquidity_score"),
        "copy_degradation_bps": metadata.get("copy_degradation_bps"),
        "winning_vote_score": metadata.get("winning_vote_score"),
        "opposing_vote_score": metadata.get("opposing_vote_score"),
        "gross_vote_edge_bps": metadata.get("gross_vote_edge_bps"),
        "evidence_source": metadata.get("evidence_source") or metadata.get("source"),
    }


def _is_copy_like_direct_family(family: str, *, strategy_id: str = "") -> bool:
    raw = f"{family} {strategy_id}".lower()
    return any(token in raw for token in COPY_LIKE_FAMILY_TOKENS)


def _metadata_float(metadata: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = _safe_float(metadata.get(name))
        if value is not None:
            return value
    return None


def _metadata_int(metadata: dict[str, Any], *names: str, default: int = 0) -> int:
    for name in names:
        value = _safe_float(metadata.get(name))
        if value is not None:
            return int(value)
    return int(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, "")))
    except (TypeError, ValueError):
        return int(default)


def _current_session_pnl_usdc(state: UiState | None) -> float:
    if state is None:
        return 0.0
    history = getattr(state, "simulation_equity_history", None) or []
    if history and isinstance(history[-1], dict):
        value = _safe_float(history[-1].get("current_pnl_usdc"))
        if value is not None:
            return value
    return _safe_float(getattr(state, "simulation_realized_pnl_usdc", 0.0)) or 0.0


def _open_quality_gated_positions_count(state: UiState) -> int:
    positions = getattr(state, "simulation_virtual_positions", {}) or {}
    if not isinstance(positions, dict):
        return 0
    count = 0
    for position in positions.values():
        if not isinstance(position, dict):
            continue
        mode = str(position.get("position_mode") or "").upper()
        family = str(position.get("strategy_family") or "").lower()
        if "EXTERNAL_GITHUB_COPY_PAPER" in mode or _is_copy_like_direct_family(family, strategy_id=str(position.get("strategy_id") or "")):
            count += 1
    return count


def _apply_direct_paper_close_order(
    state: UiState,
    order: dict[str, Any],
    *,
    delta_key: str,
    current_ms: int,
    result: dict[str, Any],
) -> None:
    coin = str(order.get("coin") or "").upper()
    side = str(order.get("side") or "").upper()
    exit_price = _safe_float(order.get("reference_price")) or 0.0
    metadata = order.get("metadata") if isinstance(order.get("metadata"), dict) else {}
    preferred_key = str(metadata.get("position_key") or "")
    if coin == "" or side not in {"LONG", "SHORT"} or exit_price <= 0:
        result["skipped_count"] += 1
        result["reasons"].append("INVALID_DIRECT_PAPER_CLOSE_FIELDS")
        return
    position_key = _find_close_position_key(state.simulation_virtual_positions, coin=coin, side=side, preferred_key=preferred_key)
    if not position_key:
        result["skipped_count"] += 1
        result["reasons"].append("NO_MATCHING_DIRECT_PAPER_POSITION_TO_CLOSE")
        state.simulation_processed_delta_keys.add(delta_key)
        return
    position = state.simulation_virtual_positions.get(position_key)
    if not isinstance(position, dict):
        result["skipped_count"] += 1
        result["reasons"].append("INVALID_DIRECT_PAPER_CLOSE_POSITION")
        state.simulation_processed_delta_keys.add(delta_key)
        return
    size = _safe_float(position.get("size")) or 0.0
    entry_price = _safe_float(position.get("entry_price") or position.get("avg_price")) or 0.0
    if size == 0 or entry_price <= 0:
        result["skipped_count"] += 1
        result["reasons"].append("INVALID_DIRECT_PAPER_CLOSE_POSITION_NUMBERS")
        state.simulation_processed_delta_keys.add(delta_key)
        return
    closed_notional = abs(size * exit_price)
    gross_pnl = (exit_price - entry_price) * size
    fees_bps = _safe_float(metadata.get("fees_bps")) if isinstance(metadata, dict) else None
    exit_costs = closed_notional * (fees_bps if fees_bps is not None else 8.0) / 10_000.0
    net_pnl = gross_pnl - exit_costs
    strategy_id = str(order.get("strategy_id") or "")
    order_id = str(order.get("order_id") or "")

    state.simulation_ledger_events.append(
        {
            "delta_key": delta_key,
            "wallet_address": strategy_id or str(position.get("wallet_address") or ""),
            "coin": coin,
            "leader_action": "FUSION_DIRECT_RUNTIME_CLOSE",
            "leader_side": side,
            "leader_price": exit_price,
            "leader_notional_usdc": closed_notional,
            "observed_at_ms": current_ms,
            "bot_replay_action": "FUSION_DIRECT_PAPER_CLOSE",
            "paper_action_type": "CLOSE",
            "status": "LOCAL_REPLAY",
            "estimated_net_pnl_usdc": round(net_pnl, 8),
            "gross_pnl_usdc": round(gross_pnl, 8),
            "fee_cost_usdc": round(exit_costs, 8),
            "copied_notional_usdt": closed_notional,
            "bot_position_size_after": 0.0,
            "matched_position_key": position_key,
            "source_delta_key": position.get("source_delta_key"),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "average_entry_price": entry_price,
            "reason": str(metadata.get("close_reason") or "EXTERNAL_GITHUB_FUSION_CLOSE_PAPER_ONLY"),
            "evidence_hash": order_id,
            "paper_mode": "PAPER_LOCAL_USDT_ONLY",
            "strategy_id": strategy_id,
            "strategy_family": str(metadata.get("profile_family") or "external_close"),
            "research_only": True,
            "simulation_only": True,
            "read_only": True,
            "external_action": False,
            "real_execution": False,
            "execution": "forbidden",
            "venue_endpoint": None,
            "secret_material_used": False,
        }
    )
    _release_processed_key_for_position(state, position)
    del state.simulation_virtual_positions[position_key]
    state.simulation_processed_delta_keys.add(delta_key)
    state.simulation_realized_pnl_usdc += net_pnl
    state.simulation_exit_costs_paid_usdc += exit_costs
    state.simulation_reproduced_exits_total += 1
    result["applied_count"] += 1


def _release_processed_key_for_position(state: UiState, position: dict[str, Any]) -> None:
    processed = getattr(state, "simulation_processed_delta_keys", None)
    if not isinstance(processed, set):
        return
    source_delta_key = str(position.get("source_delta_key") or "")
    if source_delta_key:
        processed.discard(source_delta_key)
    last_paper_ref = str(position.get("last_paper_ref") or "")
    if last_paper_ref:
        processed.discard(f"fusion-runtime-order:{last_paper_ref}")


def _find_close_position_key(
    positions: object,
    *,
    coin: str,
    side: str,
    preferred_key: str = "",
) -> str:
    if not isinstance(positions, dict):
        return ""
    if preferred_key and isinstance(positions.get(preferred_key), dict):
        return preferred_key
    for key, position in positions.items():
        if not isinstance(position, dict):
            continue
        if str(position.get("coin") or "").upper() != coin:
            continue
        pos_side = str(position.get("side") or position.get("direction") or "").upper()
        if pos_side == side:
            return str(key)
    return ""


def _safe_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return float(default)


def _trim_ledger(state: UiState) -> None:
    state.simulation_ledger_events[:] = state.simulation_ledger_events[-20_000:]


__all__ = ["apply_fusion_paper_orders_to_state"]
