"""Read-only fusion runtime bridge for the simulation status endpoint.

The heavy fusion runtime is intentionally not called from the HTML template and
not allowed to invent signals. This module only runs it when the launcher/engine
heartbeat provides explicit live input extracted upstream from real read-only
Hyperliquid data. Otherwise it returns an honest no-data payload.
"""

from __future__ import annotations

import json
from typing import Any

from hl_observer.arbitrage.triangular_graph import TriangularEdge
from hl_observer.config.settings import Settings
from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote
from hl_observer.realtime.multi_source_price_stream import PriceEvent
from hl_observer.signals.distilled_opportunity_detector import DistilledSignalCandidate
from hl_observer.strategies.fusion_runtime import FusionRuntimeInput, run_fusion_strategy_runtime
from hl_observer.ui.simulation_log_export import logs_to_send_dir
from hl_observer.ui.state import UiState
from hl_observer.utils.time import now_ms
from hl_observer.integration.opportunity_board_adapter import board_payload_from_fusion_result


FUSION_STATUS_LOG_FILENAME = "simulation_fusion_runtime_latest.json"


def build_fusion_status_payload(
    *,
    state: UiState,
    engine_status: dict[str, Any],
    scanner: dict[str, Any],
    settings: Settings | None = None,
    current_ms: int | None = None,
) -> dict[str, Any]:
    """Build a compact paper-only fusion status payload.

    The expected live input format is a top-level ``fusion_runtime_input`` object
    inside the engine heartbeat. Tests may also pass this object directly via the
    heartbeat. If it is absent, no order is simulated and the response explains
    what is missing.
    """

    current_ms = int(current_ms or now_ms())
    state_summary = _state_summary(state)
    raw_input = _raw_fusion_input(engine_status)
    base: dict[str, Any] = {
        "status": "NO_LIVE_FUSION_INPUT",
        "data_truth": "real_or_empty",
        "paper_only": True,
        "real_execution": False,
        "external_action": False,
        "source": "engine_heartbeat",
        "current_time_ms": current_ms,
        "state_summary": state_summary,
        "scanner_summary": _scanner_summary(scanner),
        "freshness": _fusion_freshness(engine_status, scanner),
        "orders_count": 0,
        "paper_engine_accepted": 0,
        "no_trade_reasons": ["NO_LIVE_FUSION_INPUT"],
        "message": (
            "Aucune entree fusion live fournie par le moteur. Le status n'invente "
            "ni wallet, ni signal, ni PnL."
        ),
    }

    if not isinstance(raw_input, dict):
        _export_latest(settings, base)
        return base

    parsed, errors = _parse_fusion_runtime_input(raw_input, current_ms=current_ms, state=state)
    if errors:
        payload = {
            **base,
            "status": "INVALID_LIVE_FUSION_INPUT",
            "no_trade_reasons": errors,
            "message": "Entree fusion presente mais invalide ou incomplete; aucun ordre paper cree.",
        }
        _export_latest(settings, payload)
        return payload

    result = run_fusion_strategy_runtime(parsed)
    result_payload = result.as_dict()
    payload = {
        **base,
        "status": "OK_LIVE_FUSION_RUNTIME",
        "message": "Runtime fusion execute en paper local depuis une entree moteur explicite.",
        "runtime": result_payload,
        "session": result_payload.get("session", {}),
        "conflict": result_payload.get("conflict", {}),
        "latency": result_payload.get("latency", {}),
        "drawdown": result_payload.get("drawdown", {}),
        "orders_count": len(result.paper_orders),
        "paper_engine_accepted": result.paper_engine.accepted_count,
        "paper_engine": result.paper_engine.as_dict(),
        "price_discrepancies_count": len(result.price_discrepancies),
        "funding_signals_count": len(result.funding_signals),
        "triangular_opportunities_count": len(result.triangular_opportunities),
        "no_trade_reasons": list(result.no_trade_reasons),
        "opportunity_board": board_payload_from_fusion_result(result, now_ms=current_ms),  # DISCO: tableau unifie cross-strategie
        "input_counts": {
            "leader_votes": len(parsed.leader_votes),
            "price_events": len(parsed.price_events),
            "funding_rows": len(parsed.funding_rows),
            "triangular_edges": len(parsed.triangular_edges),
            "latencies_ms": len(parsed.latencies_ms),
            "distilled_signal_candidates": len(parsed.distilled_signal_candidates),
        },
    }
    _export_latest(settings, payload)
    return payload


def _raw_fusion_input(engine_status: dict[str, Any]) -> dict[str, Any] | None:
    direct = engine_status.get("fusion_runtime_input")
    if isinstance(direct, dict):
        return direct
    metrics = engine_status.get("metrics")
    if isinstance(metrics, dict) and isinstance(metrics.get("fusion_runtime_input"), dict):
        return metrics["fusion_runtime_input"]
    return None


def _parse_fusion_runtime_input(
    payload: dict[str, Any],
    *,
    current_ms: int,
    state: UiState,
) -> tuple[FusionRuntimeInput, list[str]]:
    errors: list[str] = []
    votes = _parse_votes(payload.get("leader_votes"), errors)
    prices = _parse_price_events(payload.get("price_events"), errors)
    funding_rows = _parse_dict_rows(payload.get("funding_rows"), "funding_rows", errors)
    edges = _parse_triangular_edges(payload.get("triangular_edges"), errors)
    latencies = _parse_latencies(payload.get("latencies_ms"), errors)
    distilled_candidates = _parse_distilled_signal_candidates(payload.get("distilled_signal_candidates"), errors)

    if not votes:
        errors.append("NO_LEADER_VOTES")
    if not prices:
        errors.append("NO_PRICE_EVENTS")
    if errors:
        return _empty_input(current_ms=current_ms), _dedupe(errors)

    return (
        FusionRuntimeInput(
            session_id=str(payload.get("session_id") or f"ui-fusion-{current_ms}"),
            leader_votes=tuple(votes),
            price_events=tuple(prices),
            funding_rows=tuple(funding_rows),
            triangular_edges=tuple(edges),
            latencies_ms=tuple(latencies),
            peak_equity=_safe_float(payload.get("peak_equity")) or _state_peak_equity(state),
            current_equity=_safe_float(payload.get("current_equity")) or _state_current_equity(state),
            copy_ratio=_safe_float(payload.get("copy_ratio")) or 0.05,
            open_positions=tuple(_state_open_positions_for_fusion(state)),
            distilled_signal_candidates=tuple(distilled_candidates),
        ),
        [],
    )


def _empty_input(*, current_ms: int) -> FusionRuntimeInput:
    return FusionRuntimeInput(
        session_id=f"invalid-ui-fusion-{current_ms}",
        leader_votes=(),
        price_events=(),
        funding_rows=(),
        triangular_edges=(),
    )


def _parse_votes(raw: Any, errors: list[str]) -> list[LeaderVote]:
    rows: list[LeaderVote] = []
    if raw is None:
        return rows
    if not isinstance(raw, list):
        errors.append("LEADER_VOTES_NOT_LIST")
        return rows
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append(f"LEADER_VOTE_INVALID_{index}")
            continue
        wallet = str(item.get("wallet") or item.get("wallet_address") or "")
        coin = str(item.get("coin") or "").upper()
        side = str(item.get("side") or item.get("action") or "").upper()
        score = _safe_float(item.get("score")) or 1.0
        if not wallet or not coin or side not in {"LONG", "SHORT", "BUY", "SELL", "OPEN_LONG", "OPEN_SHORT"}:
            errors.append(f"LEADER_VOTE_MISSING_FIELDS_{index}")
            continue
        rows.append(
            LeaderVote(
                wallet=wallet,
                coin=coin,
                side=side,
                score=score,
                observed_at_ms=_safe_int(item.get("observed_at_ms")) or 0,
            )
        )
    return rows


def _parse_price_events(raw: Any, errors: list[str]) -> list[PriceEvent]:
    rows: list[PriceEvent] = []
    if raw is None:
        return rows
    if not isinstance(raw, list):
        errors.append("PRICE_EVENTS_NOT_LIST")
        return rows
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append(f"PRICE_EVENT_INVALID_{index}")
            continue
        source = str(item.get("source") or "")
        coin = str(item.get("coin") or "").upper()
        bid = _safe_float(item.get("bid"))
        ask = _safe_float(item.get("ask"))
        event_time_ms = _safe_int(item.get("event_time_ms"))
        if not source or not coin or bid is None or ask is None or bid <= 0 or ask <= 0 or event_time_ms is None:
            errors.append(f"PRICE_EVENT_MISSING_FIELDS_{index}")
            continue
        rows.append(PriceEvent(source=source, coin=coin, bid=bid, ask=ask, event_time_ms=event_time_ms))
    return rows


def _parse_dict_rows(raw: Any, name: str, errors: list[str]) -> list[dict[str, object]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.append(f"{name.upper()}_NOT_LIST")
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _parse_triangular_edges(raw: Any, errors: list[str]) -> list[TriangularEdge]:
    edges: list[TriangularEdge] = []
    if raw is None:
        return edges
    if not isinstance(raw, list):
        errors.append("TRIANGULAR_EDGES_NOT_LIST")
        return edges
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append(f"TRIANGULAR_EDGE_INVALID_{index}")
            continue
        base = str(item.get("base") or "")
        quote = str(item.get("quote") or "")
        rate = _safe_float(item.get("rate"))
        if not base or not quote or rate is None or rate <= 0:
            errors.append(f"TRIANGULAR_EDGE_MISSING_FIELDS_{index}")
            continue
        edges.append(TriangularEdge(base=base, quote=quote, rate=rate))
    return edges


def _parse_latencies(raw: Any, errors: list[str]) -> list[int]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.append("LATENCIES_NOT_LIST")
        return []
    latencies: list[int] = []
    for item in raw:
        value = _safe_int(item)
        if value is not None and value >= 0:
            latencies.append(value)
    return latencies


def _parse_distilled_signal_candidates(raw: Any, errors: list[str]) -> list[DistilledSignalCandidate]:
    rows: list[DistilledSignalCandidate] = []
    if raw is None:
        return rows
    if not isinstance(raw, list):
        errors.append("DISTILLED_SIGNAL_CANDIDATES_NOT_LIST")
        return rows
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append(f"DISTILLED_SIGNAL_CANDIDATE_INVALID_{index}")
            continue
        coin = str(item.get("coin") or "").upper()
        side = str(item.get("side") or "").upper()
        wallet = str(item.get("leader_wallet") or item.get("wallet") or item.get("wallet_address") or "")
        action = str(item.get("action_type") or item.get("action") or "")
        event_time_ms = _safe_int(item.get("event_time_ms") or item.get("observed_at_ms"))
        notional = _safe_float(item.get("leader_notional_usdc") or item.get("notional_usdc"))
        if not coin or side not in {"LONG", "SHORT"} or not wallet or not action or event_time_ms is None:
            errors.append(f"DISTILLED_SIGNAL_CANDIDATE_MISSING_FIELDS_{index}")
            continue
        rows.append(
            DistilledSignalCandidate(
                coin=coin,
                side=side,
                leader_wallet=wallet,
                action_type=action,
                event_time_ms=int(event_time_ms),
                leader_notional_usdc=float(notional or 0.0),
                edge_remaining_bps=_safe_float(item.get("edge_remaining_bps")),
                liquidity_score=_safe_float(item.get("liquidity_score")) or 0.5,
                leader_score=_safe_float(item.get("leader_score")) or 50.0,
                copy_degradation_bps=_safe_float(item.get("copy_degradation_bps")) or 0.0,
                source_profile=str(item.get("source_profile") or item.get("strategy_id") or "canonical"),
            )
        )
    return rows


def _state_summary(state: UiState) -> dict[str, Any]:
    positions = getattr(state, "simulation_virtual_positions", {}) or {}
    ledger = getattr(state, "simulation_ledger_events", []) or []
    return {
        "open_positions": len(positions) if isinstance(positions, dict) else 0,
        "ledger_events": len(ledger) if isinstance(ledger, list) else 0,
        "starting_equity_usdt": float(getattr(state, "simulation_starting_equity_usdt", 1000.0) or 1000.0),
        "realized_pnl_usdc": float(getattr(state, "simulation_realized_pnl_usdc", 0.0) or 0.0),
        "entries_total": int(getattr(state, "simulation_reproduced_entries_total", 0) or 0),
        "exits_total": int(getattr(state, "simulation_reproduced_exits_total", 0) or 0),
    }


def _state_open_positions_for_fusion(state: UiState) -> list[dict[str, object]]:
    positions = getattr(state, "simulation_virtual_positions", {}) or {}
    if not isinstance(positions, dict):
        return []
    rows: list[dict[str, object]] = []
    for key, raw in positions.items():
        if not isinstance(raw, dict):
            continue
        size = _safe_float(raw.get("size")) or 0.0
        entry = _safe_float(raw.get("entry_price") or raw.get("avg_price")) or 0.0
        rows.append(
            {
                "position_key": str(key),
                "coin": str(raw.get("coin") or "").upper(),
                "side": str(raw.get("side") or raw.get("direction") or ("LONG" if size > 0 else "SHORT" if size < 0 else "")),
                "size": size,
                "entry_price": entry,
                "notional_usdt": abs(size * entry),
                "strategy_id": str(raw.get("strategy_id") or raw.get("wallet_address") or raw.get("leader_wallet") or ""),
            }
        )
    return rows


def _scanner_summary(scanner: dict[str, Any]) -> dict[str, Any]:
    return {
        key: scanner.get(key)
        for key in (
            "engine_running",
            "phase",
            "wallet_candidates_total",
            "fresh_entry_deltas",
            "virtual_entries_logged",
            "virtual_refusals_logged",
            "entry_supply_bottleneck",
            "fusion_runtime_input_status",
            "fusion_runtime_recent_deltas",
            "fusion_runtime_recent_entry_deltas",
            "fusion_runtime_latest_delta_age_ms",
        )
        if key in scanner
    }


def _fusion_freshness(engine_status: dict[str, Any], scanner: dict[str, Any]) -> dict[str, Any]:
    metrics = engine_status.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    latest_age = _safe_int(metrics.get("fusion_runtime_latest_delta_age_ms"))
    recent_deltas = _safe_int(metrics.get("fusion_runtime_recent_deltas"))
    recent_entries = _safe_int(metrics.get("fusion_runtime_recent_entry_deltas"))
    status = str(
        engine_status.get("fusion_runtime_input_status")
        or metrics.get("fusion_runtime_input_status")
        or scanner.get("fusion_runtime_input_status")
        or "UNKNOWN"
    )
    if latest_age is None:
        state = "UNKNOWN"
        message = "Aucun delta local connu dans le statut fusion."
    elif latest_age <= 15_000:
        state = "FRESH"
        message = "Dernier delta local tres frais."
    elif latest_age <= 120_000:
        state = "RECENT_BUT_NOT_ENTRY"
        message = "Deltas recents visibles, mais pas forcement exploitables en entree."
    else:
        state = "STALE"
        message = "Le scanner ne nourrit plus de delta frais; attendre/retrouver le flux userFills."
    return {
        "status": status,
        "state": state,
        "message": message,
        "latest_delta_age_ms": latest_age,
        "recent_deltas": recent_deltas or 0,
        "recent_entry_deltas": recent_entries or 0,
    }


def _state_current_equity(state: UiState) -> float:
    history = getattr(state, "simulation_equity_history", None) or []
    if history and isinstance(history[-1], dict):
        value = _safe_float(history[-1].get("current_equity_usdt"))
        if value is not None and value > 0:
            return value
    return float(getattr(state, "simulation_starting_equity_usdt", 1000.0) or 1000.0) + float(
        getattr(state, "simulation_realized_pnl_usdc", 0.0) or 0.0
    )


def _state_peak_equity(state: UiState) -> float:
    values: list[float] = []
    for point in getattr(state, "simulation_equity_history", None) or []:
        if isinstance(point, dict):
            value = _safe_float(point.get("current_equity_usdt"))
            if value is not None:
                values.append(value)
    values.append(_state_current_equity(state))
    return max(values) if values else 1000.0


def _export_latest(settings: Settings | None, payload: dict[str, Any]) -> None:
    if settings is None:
        return
    snapshot = {
        "status": payload.get("status"),
        "message": payload.get("message"),
        "data_truth": payload.get("data_truth"),
        "paper_only": payload.get("paper_only"),
        "real_execution": payload.get("real_execution"),
        "external_action": payload.get("external_action"),
        "orders_count": payload.get("orders_count"),
        "paper_engine_accepted": payload.get("paper_engine_accepted"),
        "no_trade_reasons": payload.get("no_trade_reasons"),
        "state_summary": payload.get("state_summary"),
        "scanner_summary": payload.get("scanner_summary"),
        "input_counts": payload.get("input_counts"),
        "conflict": payload.get("conflict"),
        "paper_engine": payload.get("paper_engine"),
        "freshness": payload.get("freshness"),
        "updated_at_ms": now_ms(),
    }
    try:
        path = logs_to_send_dir(settings) / FUSION_STATUS_LOG_FILENAME
        path.write_text(json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return


def _safe_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _safe_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


__all__ = ["FUSION_STATUS_LOG_FILENAME", "build_fusion_status_payload"]
