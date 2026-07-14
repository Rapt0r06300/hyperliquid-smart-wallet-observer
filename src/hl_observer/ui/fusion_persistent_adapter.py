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
from hl_observer.strategies.strategy_mode import (
    GRINDER,
    classify as classify_strategy_mode,
    mode_of_position,
)
from hl_observer.ui.state import UiState

# BUG CORRIGE (audit 2026-07-11) -- CHEMIN A/B MORT.
# La liste ne contenait que ("ext_", "copy_"). Elle datait d'une epoque ou TOUTES les strategies
# etaient nommees d'apres un profil GitHub externe. Depuis le pivot shadow-only (ff7aeec), le
# catalogue externe prioritaire est VIDE : `fusion_runtime._first_available_profile()` retombe
# donc sur ses noms internes (`ws_price_discrepancy_paper`, `funding_delta_neutral_paper`,
# `triangular_paper_detection`, `distilled_whale_consensus_paper`). Aucun de ces noms ne commence
# par "ext_" ou "copy_" -> meme avec HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION=1, l'ordre
# paper d'arbitrage / funding / triangulaire etait SILENCIEUSEMENT JETE : 0 position, 0 evenement
# au ledger, 0 PnL. Le chemin de recherche A/B ne pouvait rien materialiser.
# Les moteurs INTERNES distilles sont maintenant reconnus. Le garde-fou reste entier :
#   - rien n'est materialise sans le flag A/B explicite (OFF par defaut, absent des launchers) ;
#   - le PaperEngine canonique reste le writer normal ;
#   - aucun ordre reel, jamais (paper_only=True / real_execution=False verifies plus bas).
MATERIALIZABLE_STRATEGY_PREFIXES = (
    "ext_",                  # profils GitHub externes (shadow-only par defaut)
    "copy_",                 # copy-follow / resolveur de conflit
    "ws_",                   # arbitrage de discrepance de prix (moteur interne)
    "funding_",              # funding delta-neutre (moteur interne)
    "triangular_",           # arbitrage triangulaire (moteur interne)
    "distilled_",            # consensus whale distille (moteur interne)
)
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

    _record_funding_arb_events(
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
        # le moteur est connu AVANT le gate : un budget de risque par moteur n'a de sens que si
        # l'on sait QUEL moteur demande a ouvrir.
        _mode_entrant = classify_strategy_mode(
            strategy_id=str(trade.get("strategy_id") or ""),
            source=str(decision.get("source") or "fusion_runtime_copy"),
            leader_wallet=wallet,
        )
        portfolio_refusal = _portfolio_open_refusal(
            state, new_notional_usdt=notional, coin=coin, side=side,
            strategy_mode=_mode_entrant,
        )
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
        decision_context = decision.get("decision_context") if isinstance(decision.get("decision_context"), dict) else {}
        evidence_fields = _paper_engine_evidence_fields(decision_context)
        leader_wallets_csv = str(evidence_fields.get("leader_wallets_csv") or wallet)
        _mode = classify_strategy_mode(
            strategy_id=str(trade.get("strategy_id") or ""),
            source=str(decision.get("source") or "fusion_runtime_copy"),
            leader_wallet=wallet,
        )
        state.simulation_virtual_positions[position_key] = {
            "strategy_mode": _mode,
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
            "leader_wallets_csv": leader_wallets_csv,
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
            **evidence_fields,
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
                "strategy_mode": _mode,
                "paper_action_type": "OPEN",
                "status": "LOCAL_REPLAY",
                "estimated_net_pnl_usdc": None,
                "gross_pnl_usdc": None,
                "fee_cost_usdc": round(entry_costs, 8),
                # PIEGE A DOUBLE COMPTAGE (2026-07-11). Ce cout est DEJA dans `entry_price` :
                # le PaperEngine pose entry_price = fill_price, cout d'execution inclus
                # (embedded_cost_model = fill_price_includes_spread_slippage_fee_latency).
                # `fee_cost_usdc` ci-dessus n'est qu'un REPORT, pas une seconde ponction.
                # Le soustraire du gross NOIRCIT le PnL. Un outil d'audit s'y est deja fait
                # prendre. Ce drapeau existe pour que plus personne ne s'y trompe.
                "fee_already_embedded_in_entry_price": True,
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
                **evidence_fields,
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
        _mode_entrant = classify_strategy_mode(
            strategy_id=strategy_id,
            source=str((order.get("metadata") or {}).get("profile_family")
                       if isinstance(order.get("metadata"), dict) else "external_direct_order"),
        )
        portfolio_refusal = _portfolio_open_refusal(
            state, new_notional_usdt=notional, coin=coin, side=side,
            strategy_mode=_mode_entrant,
        )
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
        _mode = classify_strategy_mode(
            strategy_id=strategy_id,
            source=str(metadata.get("profile_family") or "external_direct_order"),
        )
        state.simulation_virtual_positions[position_key] = {
            "strategy_mode": _mode,
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
                "strategy_mode": _mode,
                "paper_action_type": "OPEN",
                "status": "LOCAL_REPLAY",
                "estimated_net_pnl_usdc": None,
                "gross_pnl_usdc": None,
                "fee_cost_usdc": round(entry_costs, 8),
                # PIEGE A DOUBLE COMPTAGE (2026-07-11). Ce cout est DEJA dans `entry_price` :
                # le PaperEngine pose entry_price = fill_price, cout d'execution inclus
                # (embedded_cost_model = fill_price_includes_spread_slippage_fee_latency).
                # `fee_cost_usdc` ci-dessus n'est qu'un REPORT, pas une seconde ponction.
                # Le soustraire du gross NOIRCIT le PnL. Un outil d'audit s'y est deja fait
                # prendre. Ce drapeau existe pour que plus personne ne s'y trompe.
                "fee_already_embedded_in_entry_price": True,
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


def _record_funding_arb_events(
    state: UiState,
    *,
    runtime: dict[str, Any],
    current_ms: int,
    result: dict[str, Any],
) -> None:
    """Crédite le funding-arb paper au ledger (mode grinder, brique 2).

    Comptabilité sans double compte: OPEN débite les coûts d'entrée, ACCRUAL
    crédite le funding encaissé, CLOSE débite les coûts de sortie. Le net des
    paires = somme de ces événements, par construction.
    """

    payload = runtime.get("funding_arb")
    if not isinstance(payload, dict) or payload.get("enabled") is not True:
        return
    events = payload.get("events")
    if not isinstance(events, list):
        return
    recorded = 0
    for item in events:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "")
        if action not in {"OPEN", "ACCRUAL", "CLOSE"}:
            continue
        pair_id = str(item.get("pair_id") or "")
        coin = str(item.get("coin") or "").upper()
        if not pair_id or not coin:
            continue
        delta_key = f"funding-arb:{pair_id}:{action}:{current_ms}"
        if delta_key in state.simulation_processed_delta_keys:
            continue
        amount = float(item.get("amount_usdc") or 0.0)
        # LE TERME QUI MANQUAIT (2026-07-11). Le funding-arb n'a QU'UNE JAMBE : c'est une position
        # NUE. Son PnL comptait le funding encaisse et les couts, mais JAMAIS le mouvement du prix.
        # Un revenu de funding sans risque de marche, ca n'existe pas -- c'etait un PnL fabrique.
        _price_pnl = item.get("price_pnl_usdc")
        _price_inconnu = bool(item.get("price_pnl_unknown"))
        try:
            _price_pnl = float(_price_pnl) if _price_pnl is not None else None
        except (TypeError, ValueError):
            _price_pnl = None
        if action == "ACCRUAL":
            pnl_delta = amount
        else:
            pnl_delta = -abs(amount)
            if action == "CLOSE" and _price_pnl is not None:
                pnl_delta += _price_pnl
        state.simulation_realized_pnl_usdc += pnl_delta
        if action != "ACCRUAL":
            state.simulation_exit_costs_paid_usdc += abs(amount) if action == "CLOSE" else 0.0
            state.simulation_entry_costs_paid_usdc += abs(amount) if action == "OPEN" else 0.0
        state.simulation_ledger_events.append(
            {
                "delta_key": delta_key,
                "wallet_address": "funding_arb_paper",
                "coin": coin,
                "leader_action": f"FUNDING_ARB_{action}",
                "leader_side": "NEUTRAL",
                "leader_price": None,
                "leader_notional_usdc": float(item.get("amount_usdc") or 0.0),
                "observed_at_ms": current_ms,
                "bot_replay_action": f"FUNDING_ARB_PAPER_{action}",
                # PISTE 11 -- le funding-arb EST le Grinder. Sans ce champ il restait invisible
                # a l'attribution : son PnL se serait fondu dans "UNKNOWN".
                "strategy_mode": GRINDER,
                "paper_action_type": "FUNDING_ARB_" + action,
                "status": "LOCAL_REPLAY",
                "estimated_net_pnl_usdc": round(pnl_delta, 8),
                "gross_pnl_usdc": round(pnl_delta, 8) if action == "ACCRUAL" else None,
                "fee_cost_usdc": abs(amount) if action in {"OPEN", "CLOSE"} else 0.0,
                "copied_notional_usdt": 0.0,
                "bot_position_size_after": None,
                "reason": (
                    "INSUFFICIENT_DATA_PRICE_UNKNOWN_" + str(item.get("reason") or action)
                    if (action == "CLOSE" and _price_inconnu)
                    else str(item.get("reason") or action)
                ),
                # tracable : on voit d'ou vient chaque dollar (funding vs prix vs couts)
                "price_pnl_usdc": _price_pnl,
                "price_pnl_unknown": _price_inconnu,
                "rate_bps_per_hour": item.get("rate_bps_per_hour"),
                "pair_id": pair_id,
                "position_mode": "FUNDING_ARB_DELTA_NEUTRAL_PAPER",
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
        recorded += 1
    result["funding_arb_events_recorded"] = recorded


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


def _portfolio_open_refusal(
    state: UiState, *, new_notional_usdt: float, coin: str = "", side: str = "",
    strategy_mode: str = "",
) -> str:
    """Global portfolio guard applied after strategy-level gates.

    Individual engines can each be reasonable and still collectively overfill the
    local wallet. This guard uses the live UiState positions as the source of
    truth so the simulation cannot open more exposure than the session budget.
    """

    positions = getattr(state, "simulation_virtual_positions", {}) or {}
    if not isinstance(positions, dict):
        return ""

    # GH-01 (2026-07-13) -- LES GARDE-FOUS QU'ON CROIT AVOIR.
    #
    # Sept fois : la capacite existe, l'interrupteur est eteint, et RIEN ne se plaint. Le pire
    # cas trouve : les CINQ flags de la pile V26, codes, testes, branches -- et aucun pose par
    # un lanceur. Trois pierres tombales justifiaient meme l'enterrement d'anciens garde-fous
    # par « remplace par protections_v26 (VIVANT) »... alors qu'il ne s'executait jamais.
    #
    # Le test (`tests/test_interrupteurs.py`) verifie que le LANCEUR les pose. Mais un lanceur
    # se contourne : un `python -m hl_observer ui` a la main, une variable Windows collante...
    # Ici, on verifie a l'EXECUTION, et on le CRIE dans le contexte de decision.
    #
    # Ce n'est pas l'absence de garde-fou qui fait mal. C'est le garde-fou qu'on CROIT avoir.
    try:
        from hl_observer.risk.interrupteurs import sante as _sante_interrupteurs
        _si = _sante_interrupteurs()
        if _si.get("REELLEMENT_ETEINTS"):
            # On n'INTERDIT pas le trade (ce serait affamer le moteur pour un probleme de
            # config), mais la raison remonte au journal, au dashboard et a l'audit.
            state.derniere_alerte_interrupteurs = _si.get("alerte", "")  # type: ignore[attr-defined]
    except Exception:                                        # noqa: BLE001
        pass

    max_positions = _env_int("HYPERSMART_MAX_OPEN_POSITIONS", 12)
    if max_positions > 0 and len(positions) >= max_positions:
        return "PORTFOLIO_MAX_OPEN_POSITIONS"
    # exposition en NOTIONAL leverage: scale le budget par le levier pour garder plusieurs
    # positions (sinon 1 seule position a 400 saturerait le budget 400). Marge a risque = /levier.
    # BUG CORRIGE (audit 2026-07-11) — FAIL-OPEN : ces deux valeurs etaient PLANCHEES
    # (`if base < 1000: base = 1000` / `if lev < 10: lev = 10`). Resultat : toute tentative de
    # RESSERRER le plafond etait silencieusement REMONTEE (ex: cap 75 -> cap effectif 10 000).
    # Un garde-fou de risque ne doit JAMAIS se desserrer tout seul (deny-by-default).
    # On respecte desormais la config ; on ne remplace que les valeurs INVALIDES (<= 0) par le defaut.
    # Semantique (fix "centimes") : MAX_TOTAL_EXPOSURE_USDT = budget de MARGE ; le plafond compare
    # est en NOTIONAL, donc budget_marge x levier. Config actuelle du launcher (1000 x 10 = 10 000)
    # -> comportement live INCHANGE.
    _lev_ex = _env_float("HYPERSMART_SIMULATION_LEVERAGE", 10.0)
    if _lev_ex <= 0.0:
        _lev_ex = 10.0
    _base_ex = abs(_env_float("HYPERSMART_MAX_TOTAL_EXPOSURE_USDT", 1000.0))
    if _base_ex <= 0.0:
        _base_ex = 1000.0
    max_exposure = _base_ex * _lev_ex
    current_exposure = _current_open_exposure_usdt(positions)
    if max_exposure > 0 and current_exposure + abs(float(new_notional_usdt or 0.0)) > max_exposure:
        return "PORTFOLIO_MAX_TOTAL_EXPOSURE"

    # GARDE-FOU MANQUANT (2026-07-11) — EXPOSITION DIRECTIONNELLE **NETTE** ET CONCENTRATION.
    # Tout ce qui precede ne regarde que l'exposition BRUTE (une somme d'`abs()`). Pour ce gate,
    # 6 shorts et 1 long sont aussi "diversifies" que 7 paris opposes. Une session live a donc pu
    # accumuler 9 positions presque toutes SHORT, soit ~250 % du capital dans UN SEUL sens : ce
    # n'est pas un portefeuille, c'est le meme pari repete 9 fois. Sur le run precedent, 97 % de
    # la perte venait des shorts. On plafonne desormais le pari NET et la concentration par marche.
    try:
        from hl_observer.risk.directional_exposure import directional_refusal

        _equity = abs(_safe_float(getattr(state, "simulation_starting_equity_usdt", 1000.0)) or 1000.0)
        _dir = directional_refusal(
            positions,
            coin=str(coin or ""),
            side=str(side or ""),
            new_notional_usdt=abs(float(new_notional_usdt or 0.0)),
            equity_usdt=_equity,
        )
        if _dir:
            return _dir
    except Exception:
        pass

    # BUDGET DE RISQUE **PAR MOTEUR** (2026-07-11). Le garde-fou de session existant raisonne sur
    # UN SEUL PnL : si le Sniper perd 40 $, le Grinder est puni aussi -- alors que son mecanisme
    # (funding delta-neutre) n'a rien a voir avec la cause de la perte. Et un Grinder qui gagne
    # MASQUERAIT un Sniper qui saigne. Chaque moteur repond desormais de SES pertes.
    try:
        from hl_observer.risk.engine_risk_budget import engine_budget_refusal

        _mode = str(strategy_mode or "").upper()
        if _mode:
            _equity_b = abs(_safe_float(getattr(state, "simulation_starting_equity_usdt", 1000.0)) or 1000.0)
            _budget = engine_budget_refusal(
                getattr(state, "simulation_ledger_events", None) or [],
                moteur=_mode,
                equity_usdt=_equity_b,
            )
            if _budget:
                return _budget
    except Exception:
        pass                                  # jamais bloquant : un garde-fou ne casse pas la boucle

    # T3b (2026-07-12) — CORRELATION DE GROUPE. Le garde-fou directionnel ci-dessus plafonne le
    # NET total et la concentration PAR COIN. Il traite donc BTC-long et ETH-long comme DEUX paris
    # independants. Ils ne le sont pas : ce sont ~0,9 du meme pari. `portfolio_correlation` le dit
    # dans sa 1re ligne — « 7 positions LONG sur des alts correles != 7 paris » — et il etait
    # MORT (importe seulement par integration/risk_quality_gate, mort lui aussi).
    # Nos 19 ouvertures SHORT sur 21 sont la version realisee de cette panne.
    #
    # ⚠️ DEUX PIEGES MORTELS, EVITES DE JUSTESSE — a lire avant de toucher a ce bloc.
    #
    # 1) `correlation_open_refusal` a un defaut `max_group_net_exposure_usdt = 120.0`. Notre
    #    notionnel est de **500 $ par trade** (marge 50 x levier 10). Branche tel quel, le
    #    garde-fou aurait refuse **100 % des entrees** : UNE seule position depasse deja 120.
    #    C'est mot pour mot le bug « 0 trade GARANTI par arithmetique » du 11/07. On exprime
    #    donc le plafond en **% de l'equity**, comme les autres caps (NET 100 %, coin 60 %).
    #    Un groupe correle doit etre plafonne PLUS HAUT qu'un coin seul (60 %) et PLUS BAS que
    #    le net total (100 %) -> 80 % par defaut.
    #
    # 2) Le module exige `side` en MAJUSCULES ("LONG"/"SHORT") et rend `CORR_INVALID_SIDE`
    #    sinon. Un runtime qui dit "buy"/"long" aurait fait refuser TOUT. On normalise ici ;
    #    et si le sens reste indechiffrable, on **passe** ce garde-fou (les autres s'appliquent
    #    toujours) : bloquer 100 % des entrees sur un desaccord de vocabulaire serait pire que
    #    le risque qu'on cherche a couvrir.
    try:
        from hl_observer.risk.portfolio_correlation import correlation_open_refusal

        _cote = _normaliser_sens(side)
        if _cote:
            _equity_c = abs(_safe_float(getattr(state, "simulation_starting_equity_usdt", 1000.0)) or 1000.0)
            _pct_grp = _env_float("HYPERSMART_MAX_GROUP_NET_EXPOSURE_PCT", 80.0)
            _cap_grp = _equity_c * max(0.0, _pct_grp) / 100.0
            if _cap_grp > 0.0:
                _corr = correlation_open_refusal(
                    _positions_as_rows(positions),
                    coin=str(coin or ""),
                    side=_cote,
                    new_notional_usdt=abs(float(new_notional_usdt or 0.0)),
                    max_group_net_exposure_usdt=_cap_grp,
                )
                if _corr:
                    return _corr
    except Exception:
        pass

    # T3b (2026-07-12) — ANTI-SURTRADING. `max_positions` (plus haut) plafonne les positions
    # SIMULTANEES ; rien ne plafonnait le nombre de trades PAR JOUR. Le firehose V27 est concu
    # pour maximiser les signaux : le surtrading est structurellement possible.
    # HONNETETE : a nos volumes (21 trades sur tout un run), ce plafond NE MORD PAS aujourd'hui.
    # C'est un disjoncteur : inutile jusqu'au jour ou il est indispensable.
    #
    # ⚠️ 3e PIEGE MORTEL, attrape par le test `..._LAISSE_PASSER_un_pari_non_correle`.
    # `can_open` fait `if trades_today >= budget.max_trades_per_day: REFUSE`. Avec un plafond
    # a **0** (ce que j'entendais comme « pas de plafond »), ca donne `0 >= 0` -> VRAI ->
    # **refus de 100 % des entrees**. Encore le bug « 0 trade GARANTI par arithmetique ».
    # Un plafond <= 0 signifie donc explicitement AUCUN PLAFOND : on saute le garde-fou.
    try:
        from hl_observer.risk.trade_budget import TradeBudget, can_open

        _max_jour = _env_int("HYPERSMART_MAX_TRADES_PER_DAY", 40)
        if _max_jour > 0:
            _budget_trades = TradeBudget(
                max_concurrent=_env_int("HYPERSMART_MAX_OPEN_POSITIONS", 12),
                max_trades_per_day=_max_jour,
                daily_profit_target_pct=_env_float("HYPERSMART_DAILY_PROFIT_TARGET_PCT", 0.0),
            )
            _ok, _why = can_open(
                _budget_trades,
                open_positions=len(positions),
                trades_today=_opens_today(getattr(state, "simulation_ledger_events", None) or []),
                day_pnl_pct=_day_pnl_pct(state),
            )
            if not _ok:
                return f"TRADE_BUDGET_{_why}"
    except Exception:
        pass

    # T3c (2026-07-12) — LE GARDE-FOU QUI AURAIT EMPECHE LE BUG DES -64 $.
    #
    # L'autopsie du 11/07 : « TP rabote a 28 bps pour 13 bps de frais -> breakeven 87 % ->
    # perte GARANTIE ». La correction avait ete de changer la CONFIG. **Rien n'empechait la
    # rechute.** Et il y a pire, mesure aujourd'hui :
    #
    #     config du LANCEUR : TP=110, SL=60, cout=12  ->  breakeven = 72/170 = 42 %  ... OK
    #     DEFAUT DU CODE    : TP=30,  SL=40, cout=12  ->  breakeven = 52/70  = 74 %  ... PERTE GARANTIE
    #
    # Si le flag du lanceur disparait -- ce qui est DEJA arrive deux fois (poller L2, funding) --
    # le code retombe SILENCIEUSEMENT sur une configuration perdante. Ce garde-fou transforme
    # la perte silencieuse en REFUS BRUYANT : on ne trade pas une structure de sortie dont le
    # winrate d'equilibre est hors d'atteinte.
    #
    # Avec la config live (42 %), il NE MORD PAS -- c'est teste dans les deux sens.
    try:
        from hl_observer.paper_trading.barrier_calibration import breakeven_winrate
        from hl_observer.paper_trading.sltp_runtime import sltp_config_from_env

        _cfg = sltp_config_from_env()
        if _cfg is not None:
            _tp = abs(float(getattr(_cfg, "take_profit_bps", 0.0) or 0.0))
            _sl = abs(float(getattr(_cfg, "stop_loss_bps", 0.0) or 0.0))
            _cout = abs(_env_float("HYPERSMART_SIMULATION_COST_BPS", 12.0))
            _plafond = _env_float("HYPERSMART_MAX_BREAKEVEN_WINRATE_PCT", 60.0)
            if _tp > 0.0 and _sl > 0.0 and _plafond > 0.0:
                _be = breakeven_winrate(_tp, _sl, _cout) * 100.0
                if _be > _plafond:
                    return (
                        "BARRIERS_BREAKEVEN_WINRATE_IMPOSSIBLE"
                        f"({_be:.0f}pct_needed_max_{_plafond:.0f}pct"
                        f"_tp{_tp:.0f}_sl{_sl:.0f}_cost{_cout:.0f})"
                    )
    except Exception:
        pass

    return ""


def _normaliser_sens(side: Any) -> str:
    """-> "LONG" | "SHORT" | "" (indechiffrable).

    Le runtime ecrit le sens de plusieurs facons selon le moteur (long/LONG/buy/B/+1...).
    `portfolio_correlation` n'accepte que LONG/SHORT et rend CORR_INVALID_SIDE sinon : sans
    cette normalisation, un simple desaccord de vocabulaire aurait refuse TOUTES les entrees.
    """
    s = str(side or "").strip().lower()
    if s in ("long", "buy", "b", "l", "+1", "1", "bid"):
        return "LONG"
    if s in ("short", "sell", "s", "-1", "ask"):
        return "SHORT"
    return ""


def _positions_as_rows(positions: dict[Any, Any]) -> list[dict]:
    """`portfolio_correlation` attend une liste de dicts {coin, side, notional_usdt}.

    Le runtime garde ses positions dans un dict indexe par cle. On adapte ICI, au point de
    branchement, plutot que de tordre le garde-fou : un garde-fou pur reste pur.
    """
    rows: list[dict] = []
    for key, pos in (positions or {}).items():
        if not isinstance(pos, dict):
            continue
        coin = str(pos.get("coin") or "").upper()
        if not coin and isinstance(key, str) and "|" in key:
            parts = key.split("|")
            coin = parts[1].upper() if len(parts) > 1 else ""
        notional = _safe_float(pos.get("notional_usdt") or pos.get("copied_notional_usdt")) or 0.0
        rows.append({
            "coin": coin,
            "side": _normaliser_sens(pos.get("side") or pos.get("direction")),
            "notional_usdt": abs(float(notional)),
        })
    return rows


def _opens_today(ledger_events: list) -> int:
    """Nombre d'OUVERTURES depuis minuit UTC, lu au LEDGER (jamais un compteur en memoire).

    Le ledger est la source de verite du PnL (CLAUDE.md) ; il l'est aussi du compte de trades.
    Un compteur separe divergerait au premier redemarrage.
    """
    import time as _t

    minuit_ms = int(_t.time() // 86_400) * 86_400 * 1000
    n = 0
    for ev in ledger_events or []:
        if not isinstance(ev, dict):
            continue
        kind = str(ev.get("event") or ev.get("type") or "").upper()
        if "OPEN" not in kind:
            continue
        ts = _safe_float(ev.get("ts_ms") or ev.get("timestamp_ms") or ev.get("ts")) or 0.0
        if ts >= minuit_ms:
            n += 1
    return n


def _day_pnl_pct(state: UiState) -> float:
    """PnL du jour en % de l'equity de depart. 0.0 si inconnu -> le verrou de gain ne mord pas
    (il est de toute facon DESACTIVE par defaut : HYPERSMART_DAILY_PROFIT_TARGET_PCT=0)."""
    equity0 = abs(_safe_float(getattr(state, "simulation_starting_equity_usdt", 1000.0)) or 1000.0)
    if equity0 <= 0:
        return 0.0
    realized = _safe_float(getattr(state, "simulation_realized_pnl_usdt", 0.0)) or 0.0
    return float(realized) / equity0 * 100.0


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
    # C'ETAIT LE VRAI PLAFOND (cause finale prouvee live): tout notional etait clampe a
    # MAX_POSITION_USDT=40 ICI, au point de materialisation -> quel que soit le levier calcule
    # en amont, la position affichee restait a 40 = centimes. On traite desormais l'entrant
    # comme la MARGE (plafonnee a 40) et on applique le LEVIER: notional position = marge x levier.
    # SIZING REEL (demande Flo "comme si on tradait en vrai"): on ne matche PAS la taille $
    # derisoire du leader (~40); on alloue NOTRE marge par trade x levier, comme un compte perp
    # reel. Autoritaire (dernier gate). Robuste aux valeurs "collees" dans l'env Windows: on
    # PLANCHE la marge a 100 et le levier a 10 -> notional position >= 100 x 10 = 1000.
    # GRINDER (correction Flo: $1000/position empechait le grinder). Beaucoup de PETITES
    # positions gagnantes: marge PETITE (<=40) x levier -> ex 40 x 10 = 400. Le PnL vient du
    # VOLUME (plein de positions) + funding, PAS de positions geantes. Le levier evite les centimes.
    # BUG CORRIGE (audit 2026-07-11) : `if lev < 5: lev = 10` FORCAIT le levier -> impossible de
    # simuler a levier 1 ou 2 (la config etait ignoree). On ne corrige plus que l'INVALIDE (<= 0).
    lev = _env_float("HYPERSMART_SIMULATION_LEVERAGE", 10.0)
    if lev <= 0.0:
        lev = 10.0
    # MODELE REEL (Flo prouve a l'ecran: notional $50 -> PnL -0.12 = centimes). Le $50 est la
    # MARGE (capital a risque par position), PAS le notional. A 10x: notional = 50 x 10 = 500
    # -> PnL = 500 x Dprix -> DES DOLLARS, comme un perp reel. Solde 1000 / marge 50 = 20 positions.
    # (Avant: margin clampe a 12 PUIS notional clampe a 50 -> double bride = centimes garantis.)
    margin_cap = abs(_env_float("HYPERSMART_MAX_POSITION_USDT", 50.0))
    if margin_cap <= 0.0:      # idem : seule une valeur INVALIDE retombe sur le defaut
        margin_cap = 50.0
    clean_notional = max(0.0, float(notional or 0.0))
    clean_quantity = abs(float(quantity or 0.0))
    if margin_cap <= 0 or entry_price <= 0 or clean_notional <= 0:
        return {"notional": clean_notional, "quantity": clean_quantity, "cap_applied": False}
    margin = margin_cap                            # marge FIXE = notre capital par position ($50), pas la taille derisoire du leader
    lev_notional = margin * lev                    # notional position = marge x levier (= $500 a 10x) -> PnL en DOLLARS
    lev_quantity = lev_notional / float(entry_price)
    return {"notional": round(lev_notional, 8), "quantity": round(lev_quantity, 12), "margin": round(margin, 8), "cap_applied": True}


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


def _paper_engine_evidence_fields(context: dict[str, Any]) -> dict[str, Any]:
    wallets_raw = context.get("leader_wallets")
    if isinstance(wallets_raw, (list, tuple, set)):
        wallets = tuple(dict.fromkeys(str(value).lower() for value in wallets_raw if str(value).strip()))
    else:
        wallets = tuple(
            dict.fromkeys(
                value.strip().lower()
                for value in str(wallets_raw or context.get("leader_wallet") or "").split(",")
                if value.strip()
            )
        )
    consensus = _safe_float(context.get("consensus_wallets"))
    if consensus is None:
        consensus = float(len(wallets))
    return {
        "edge_remaining_bps": context.get("edge_remaining_bps"),
        "signal_age_ms": context.get("signal_age_ms"),
        "leader_wallets_count": int(max(0.0, consensus)),
        "leader_wallets_csv": ",".join(wallets),
        "liquidity_score": context.get("liquidity_score"),
        "copy_degradation_bps": context.get("copy_degradation_bps"),
        "spread_bps": context.get("spread_bps"),
        "estimated_slippage_bps": context.get("estimated_slippage_bps"),
        "top_depth_usdt": context.get("top_depth_usdt"),
        "wallet_score": context.get("wallet_score"),
        "signal_score": context.get("signal_score"),
        "leader_event_time_ms": context.get("leader_event_time_ms"),
        "edge_source": context.get("edge_source"),
        "edge_is_empirical": context.get("edge_is_empirical"),
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
            "strategy_mode": mode_of_position(position),
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
