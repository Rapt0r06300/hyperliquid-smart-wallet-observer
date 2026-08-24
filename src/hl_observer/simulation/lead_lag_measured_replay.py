"""Strict measured Lead-Lag replay from recorded public execution truth.

This path exists specifically for the economic objective.  It does not trust the
legacy ``liquidite=1.0`` proxy and does not infer executable capacity from a
price.  A candidate can become ``LIQUIDATABLE_NET`` only when:

* the Binance shock is detected from the recorded trade tape;
* a real recorded Hyperliquid L2 snapshot is available at the trigger;
* entry is priced only after a measured local runtime-latency P95;
* entry and exit top-of-book capacity each cover the full paper notional;
* executable bid/ask spread and configured fees reconcile exactly to PnL.

Latency is embedded in the delayed entry price and therefore is not subtracted a
second time as a synthetic bps penalty.  Missing latency evidence or L2 coverage
fails closed.  The module is local/read-only and has no execution surface.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import statistics
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.backtesting import lead_lag_shadow
from hl_observer.mega_cablage.replay_driver import separer_par_episodes
from hl_observer.ops import lab_metriques as M

DEFAULT_DECISIONS = Path("runtime") / "data" / "lead_lag_event_decisions.jsonl"
DEFAULT_MIN_LATENCY_SAMPLES = 20
DEFAULT_MAX_BOOK_AGE_MS = 750.0
DEFAULT_MAX_EXECUTION_OBSERVATION_DELAY_MS = 750.0
DEFAULT_FEE_BPS = 9.0
LATENCY_KIND_LOCAL_MONOTONIC = "LOCAL_MONOTONIC_DISPATCH"


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _percentile_nearest_rank(values: list[float], percentile: float) -> float | None:
    clean = sorted(value for value in values if math.isfinite(value) and value >= 0)
    if not clean:
        return None
    rank = max(1, math.ceil(float(percentile) * len(clean)))
    return clean[min(len(clean), rank) - 1]


def load_runtime_latency_evidence(
    root: str | Path,
    *,
    min_samples: int = DEFAULT_MIN_LATENCY_SAMPLES,
    max_lines: int = 100_000,
) -> dict[str, Any]:
    """Read measured event-loop latency; never invent a zero-latency default."""
    path = Path(root) / DEFAULT_DECISIONS
    values: list[float] = []
    total = 0
    invalid = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        lines = []
    if max_lines > 0:
        lines = lines[-max_lines:]
    for line in lines:
        try:
            row = json.loads(line)
        except (TypeError, ValueError):
            invalid += 1
            continue
        if not isinstance(row, Mapping):
            invalid += 1
            continue
        total += 1
        if (
            row.get("sample_only") is not True
            or row.get("latency_kind") != LATENCY_KIND_LOCAL_MONOTONIC
        ):
            continue
        latency = _number(row.get("latency_ms"))
        if latency is None or latency < 0:
            continue
        values.append(float(latency))
    p95 = _percentile_nearest_rank(values, 0.95)
    measured = len(values) >= max(1, int(min_samples)) and p95 is not None
    return {
        "schema_version": "hypersmart.lead_lag_runtime_latency.v2",
        "path": DEFAULT_DECISIONS.as_posix(),
        "rows_seen": total,
        "samples": len(values),
        "invalid_rows": invalid,
        "min_samples": int(min_samples),
        "p50_ms": round(float(statistics.median(values)), 6) if values else None,
        "p95_ms": round(float(p95), 6) if p95 is not None else None,
        "max_ms": round(max(values), 6) if values else None,
        "measured": measured,
        "read_only": True,
        "real_execution": False,
    }


def _latest_at_or_before(
    rows: list[Mapping[str, Any]],
    target_ms: float,
    *,
    max_age_ms: float,
) -> Mapping[str, Any] | None:
    if not rows:
        return None
    times = [int(row.get("ts_ms") or 0) for row in rows]
    index = bisect.bisect_right(times, int(target_ms)) - 1
    if index < 0:
        return None
    row = rows[index]
    age = float(target_ms) - float(row.get("ts_ms") or 0)
    if age < 0 or age > float(max_age_ms):
        return None
    return row


def _first_at_or_after(
    rows: list[Mapping[str, Any]],
    target_ms: float,
    *,
    max_delay_ms: float,
) -> Mapping[str, Any] | None:
    if not rows:
        return None
    times = [int(row.get("ts_ms") or 0) for row in rows]
    index = bisect.bisect_left(times, int(math.ceil(target_ms)))
    if index >= len(rows):
        return None
    row = rows[index]
    delay = float(row.get("ts_ms") or 0) - float(target_ms)
    if delay < 0 or delay > float(max_delay_ms):
        return None
    return row


def _book_for_execution(
    rows: list[Mapping[str, Any]],
    target_ms: float,
    *,
    max_age_ms: float,
    max_delay_ms: float,
) -> tuple[Mapping[str, Any], float, str] | None:
    """Select a causal executable book without pretending a stale mark is current.

    The latest already-observed book is executable at ``target_ms`` while it is
    still fresh.  Otherwise the replay waits for the first bounded subsequent
    observation and moves the execution timestamp to that observation.  The
    latter is delayed execution, not look-ahead at the original target.
    """

    latest = _latest_at_or_before(rows, target_ms, max_age_ms=max_age_ms)
    if latest is not None:
        return latest, float(target_ms), "LAST_CAUSAL_FRESH"
    following = _first_at_or_after(rows, target_ms, max_delay_ms=max_delay_ms)
    if following is None:
        return None
    observed_ms = float(following.get("ts_ms") or 0)
    return following, observed_ms, "NEXT_OBSERVED_BOUNDED"


def _mid(book: Mapping[str, Any]) -> float:
    return 0.5 * (float(book["bid"]) + float(book["ask"]))


def _trade_identity(event: Mapping[str, Any]) -> str:
    payload = {
        "coin": event.get("coin"),
        "direction": event.get("direction"),
        "trigger_ts_ms": event.get("trigger_ts_ms"),
        "entry_ts_ms": event.get("entry_ts_ms"),
        "exit_ts_ms": event.get("exit_ts_ms"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _settle(
    *,
    coin: str,
    direction: int,
    trigger_ts_ms: int,
    detection_book: Mapping[str, Any],
    entry_book: Mapping[str, Any],
    exit_book: Mapping[str, Any],
    entry_execution_ts_ms: float,
    exit_execution_ts_ms: float,
    notional_usd: float,
    fee_bps: float,
    measured_latency_ms: float,
    entry_book_selection: str,
    exit_book_selection: str,
) -> dict[str, Any]:
    entry_mid = _mid(entry_book)
    exit_mid = _mid(exit_book)
    detection_mid = _mid(detection_book)
    if direction > 0:
        entry_px = float(entry_book["ask"])
        exit_px = float(exit_book["bid"])
        entry_capacity = float(entry_book.get("ask_top_usd") or 0.0)
        exit_capacity = float(exit_book.get("bid_top_usd") or 0.0)
        executable_before_fees_bps = (exit_px - entry_px) / entry_px * 1e4
    else:
        entry_px = float(entry_book["bid"])
        exit_px = float(exit_book["ask"])
        entry_capacity = float(entry_book.get("bid_top_usd") or 0.0)
        exit_capacity = float(exit_book.get("ask_top_usd") or 0.0)
        executable_before_fees_bps = (entry_px - exit_px) / entry_px * 1e4

    gross_entry_bps = float(direction) * (exit_mid - entry_mid) / entry_mid * 1e4
    spread_cost_bps = gross_entry_bps - executable_before_fees_bps
    # The execution price is selected *after* measured latency. Charging another
    # latency stress here would double count the same delay.
    latency_cost_bps = 0.0
    slippage_bps = 0.0
    capacity_ratio = min(entry_capacity, exit_capacity) / float(notional_usd)
    full_fill = capacity_ratio >= 1.0
    net_bps = executable_before_fees_bps - float(fee_bps)
    gross_usd = gross_entry_bps / 1e4 * float(notional_usd)
    fees_usd = float(fee_bps) / 1e4 * float(notional_usd)
    spread_usd = spread_cost_bps / 1e4 * float(notional_usd)
    slippage_usd = slippage_bps / 1e4 * float(notional_usd)
    latency_usd = latency_cost_bps / 1e4 * float(notional_usd)
    pnl_usd = executable_before_fees_bps / 1e4 * float(notional_usd) - fees_usd
    reconciled = math.isclose(
        gross_usd - fees_usd - spread_usd - slippage_usd - latency_usd,
        pnl_usd,
        abs_tol=1e-7,
    )
    event = {
        "coin": str(coin).upper(),
        "direction": int(direction),
        "trigger_ts_ms": int(trigger_ts_ms),
        "entry_ts_ms": int(math.ceil(entry_execution_ts_ms)),
        "exit_ts_ms": int(math.ceil(exit_execution_ts_ms)),
        "entry_book_observed_ts_ms": int(entry_book["ts_ms"]),
        "exit_book_observed_ts_ms": int(exit_book["ts_ms"]),
        "detection_mid": detection_mid,
        "entry_mid": entry_mid,
        "exit_mid": exit_mid,
        "entry_px": entry_px,
        "exit_px": exit_px,
        "entry_capacity_usd": entry_capacity,
        "exit_capacity_usd": exit_capacity,
        "capacity_ratio": capacity_ratio,
        "gross_bps": gross_entry_bps,
        "fees_bps": float(fee_bps),
        "spread_bps": spread_cost_bps,
        "slippage_bps": slippage_bps,
        "latency_bps": latency_cost_bps,
        "net_bps": net_bps,
        "gross_pnl_usd": gross_usd,
        "fees_usd": fees_usd,
        "spread_cost_usd": spread_usd,
        "slippage_cost_usd": slippage_usd,
        "latency_cost_usd": latency_usd,
        "pnl_usd": pnl_usd,
        "measured_runtime_latency_ms": float(measured_latency_ms),
        "actual_entry_delay_ms": float(entry_execution_ts_ms) - float(trigger_ts_ms),
        "entry_book_age_ms": float(entry_execution_ts_ms) - float(entry_book["ts_ms"]),
        "exit_book_age_ms": float(exit_execution_ts_ms) - float(exit_book["ts_ms"]),
        "entry_book_selection": str(entry_book_selection),
        "exit_book_selection": str(exit_book_selection),
        "latency_embedded_in_entry_price": True,
        "top_level_capacity_measured": True,
        "full_fill": full_fill,
        "economic_reconciled": reconciled,
        "LIQUIDATABLE_NET": bool(full_fill and reconciled),
        "paper_read_only": True,
        "real_execution": False,
    }
    event["trade_id"] = _trade_identity(event)
    return event


def _segment_summary(events: list[dict[str, Any]], *, costs_measured: bool, equity: float) -> dict[str, Any]:
    ledger: list[dict[str, Any]] = []
    filled: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates = 0
    missed = 0
    for event in events:
        trade_id = str(event.get("trade_id") or "")
        ledger.append({
            "evt": "SIGNAL",
            "ts": int(event.get("trigger_ts_ms") or 0),
            "coin": event.get("coin"),
            "signe": event.get("direction"),
            "edge_prevu_bps": event.get("expected_net_bps"),
            "trade_id": trade_id,
        })
        if event.get("decision") != "TRADE":
            ledger.append({"evt": "NO_TRADE", "raison": event.get("decision"), "trade_id": trade_id})
            continue
        if trade_id in seen:
            duplicates += 1
            ledger.append({"evt": "NO_TRADE", "raison": "DUPLICATE_TRADE_ID", "trade_id": trade_id})
            continue
        seen.add(trade_id)
        if event.get("full_fill") is not True:
            missed += 1
            ledger.append({"evt": "MISSED_FILL", "raison": "TOP_CAPACITY_INSUFFICIENT", "trade_id": trade_id})
            continue
        filled.append(event)
        ledger.extend([
            {"evt": "ENTREE", "ts": event["entry_ts_ms"], "trade_id": trade_id, "prix": event["entry_px"]},
            {"evt": "SORTIE", "ts": event["exit_ts_ms"], "trade_id": trade_id, "prix": event["exit_px"], "net_bps": event["net_bps"]},
            {"evt": "PNL", "trade_id": trade_id, "pnl_usd": event["pnl_usd"], "LIQUIDATABLE_NET": bool(costs_measured and event["LIQUIDATABLE_NET"])},
        ])

    nets = [float(event["pnl_usd"]) for event in filled]
    gross = sum(float(event["gross_pnl_usd"]) for event in filled)
    fees = sum(float(event["fees_usd"]) for event in filled)
    spread = sum(float(event["spread_cost_usd"]) for event in filled)
    slippage = sum(float(event["slippage_cost_usd"]) for event in filled)
    latency = sum(float(event["latency_cost_usd"]) for event in filled)
    net = sum(nets)
    curve = [float(equity)]
    for value in nets:
        curve.append(curve[-1] + value)
    contributions: dict[str, float] = {}
    for event in filled:
        coin = str(event["coin"])
        contributions[coin] = contributions.get(coin, 0.0) + float(event["pnl_usd"])
    trade_ids = [str(event["trade_id"]) for event in filled]
    return {
        "net": round(net, 8),
        "gross_pnl_usd": round(gross, 8),
        "fees_usd": round(fees, 8),
        "spread_cost_usd": round(spread, 8),
        "slippage_cost_usd": round(slippage, 8),
        "latency_cost_usd": round(latency, 8),
        "notional": round(len(filled) * (float(filled[0].get("notional_usd") or 0.0) if filled else 0.0), 8),
        "fills": len(filled),
        "missed": missed,
        "opened_positions": len(filled),
        "closed_positions": len(filled),
        "nets_episodes": nets,
        "contributions": contributions,
        "ledger": ledger,
        "trade_ids": trade_ids,
        "trade_ids_count": len(trade_ids),
        "trade_ids_sha256": hashlib.sha256("\n".join(trade_ids).encode("utf-8")).hexdigest(),
        "duplicate_trade_ids": duplicates,
        "max_drawdown_usd": M.drawdown(curve),
        "hit_rate": round(sum(value > 0 for value in nets) / len(nets), 8) if nets else None,
        "LIQUIDATABLE_NET": bool(
            filled
            and costs_measured
            and all(event.get("LIQUIDATABLE_NET") is True for event in filled)
        ),
    }


def _raw_observation_diagnostics(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe the causal executable baseline without admitting its PnL.

    These aggregates answer whether the raw mechanism has any economic promise
    after observed bid/ask and fees.  They deliberately bypass the prior-only
    admission rule for diagnosis, so they can never be used as certified PnL or
    make a train variant eligible.
    """
    reconciled_full = [
        event
        for event in events
        if event.get("economic_reconciled") is True
        and event.get("full_fill") is True
        and _number(event.get("pnl_usd")) is not None
    ]
    nets = [float(event["pnl_usd"]) for event in reconciled_full]
    net_bps = [float(event["net_bps"]) for event in reconciled_full]
    gross = sum(float(event["gross_pnl_usd"]) for event in reconciled_full)
    fees = sum(float(event["fees_usd"]) for event in reconciled_full)
    spread = sum(float(event["spread_cost_usd"]) for event in reconciled_full)
    slippage = sum(float(event["slippage_cost_usd"]) for event in reconciled_full)
    latency = sum(float(event["latency_cost_usd"]) for event in reconciled_full)
    net = sum(nets)
    positive = sum(value > 0.0 for value in nets)
    negative = sum(value < 0.0 for value in nets)
    gross_profit = sum(value for value in nets if value > 0.0)
    gross_loss = -sum(value for value in nets if value < 0.0)
    first_trigger = min(
        (int(event["trigger_ts_ms"]) for event in reconciled_full),
        default=None,
    )
    last_trigger = max(
        (int(event["trigger_ts_ms"]) for event in reconciled_full),
        default=None,
    )
    total_costs = fees + spread + slippage + latency
    return {
        "diagnostic_only": True,
        "selection_eligible": False,
        "not_admitted_pnl": True,
        "counted_as_certified_pnl": False,
        "observations": len(events),
        "economically_reconciled_observations": sum(
            event.get("economic_reconciled") is True for event in events
        ),
        "full_fill_observations": len(reconciled_full),
        "capacity_rejected_observations": sum(
            event.get("full_fill") is not True for event in events
        ),
        "positive_net_observations": positive,
        "negative_net_observations": negative,
        "flat_net_observations": len(nets) - positive - negative,
        "gross_pnl_usd_if_all_executable_taken": round(gross, 8),
        "fees_usd_if_all_executable_taken": round(fees, 8),
        "spread_cost_usd_if_all_executable_taken": round(spread, 8),
        "slippage_cost_usd_if_all_executable_taken": round(slippage, 8),
        "latency_cost_usd_if_all_executable_taken": round(latency, 8),
        "total_costs_usd_if_all_executable_taken": round(total_costs, 8),
        "net_pnl_usd_if_all_executable_taken": round(net, 8),
        "mean_net_pnl_usd": round(statistics.fmean(nets), 8) if nets else None,
        "mean_net_bps": round(statistics.fmean(net_bps), 8) if net_bps else None,
        "median_net_bps": round(statistics.median(net_bps), 8) if net_bps else None,
        "min_net_bps": round(min(net_bps), 8) if net_bps else None,
        "max_net_bps": round(max(net_bps), 8) if net_bps else None,
        "hit_rate": round(positive / len(nets), 8) if nets else None,
        "profit_factor": (
            round(gross_profit / gross_loss, 8) if gross_loss > 0.0 else None
        ),
        "first_trigger_ts_ms": first_trigger,
        "last_trigger_ts_ms": last_trigger,
        "observed_span_ms": (
            last_trigger - first_trigger
            if first_trigger is not None and last_trigger is not None
            else None
        ),
        "reconciliation_error_usd": round(net - (gross - total_costs), 10),
    }


def replay_measured_lead_lag(
    tape: Mapping[str, Mapping[str, list]],
    l2_history: Mapping[str, list[Mapping[str, Any]]],
    *,
    shock_threshold_bps: float,
    horizon_ms: int,
    latency_evidence: Mapping[str, Any],
    notional_usd: float = 100.0,
    fee_bps: float = DEFAULT_FEE_BPS,
    min_history: int = 5,
    min_expected_net_bps: float = 0.0,
    direction_multiplier: int = 1,
    max_book_age_ms: float = DEFAULT_MAX_BOOK_AGE_MS,
    max_execution_observation_delay_ms: float = DEFAULT_MAX_EXECUTION_OBSERVATION_DELAY_MS,
    min_episodes: int = 5,
    equity: float = 1000.0,
) -> dict[str, Any]:
    """Replay strictly executable episodes with prior-only admission edge."""
    if int(direction_multiplier) not in (-1, 1):
        raise ValueError("direction_multiplier must be -1 or 1")
    primary_direction_policy = (
        "SHOCK_CONTINUATION" if int(direction_multiplier) == 1 else "EXTREME_SHOCK_REVERSAL"
    )
    placebo_direction_policy = (
        "EXTREME_SHOCK_REVERSAL" if int(direction_multiplier) == 1 else "SHOCK_CONTINUATION"
    )
    latency_measured = latency_evidence.get("measured") is True
    latency_p95 = _number(latency_evidence.get("p95_ms"))
    # Research replay may still diagnose coverage with a conservative fallback,
    # but it can never become liquidatable while latency evidence is missing.
    applied_latency_ms = float(latency_p95 if latency_p95 is not None else max_book_age_ms)
    candidates: list[dict[str, Any]] = []
    direction_flip_diagnostics: list[dict[str, Any]] = []
    coverage = {
        "shocks_seen": 0,
        "missing_detection_book": 0,
        "missing_entry_book": 0,
        "missing_exit_book": 0,
        "observable": 0,
        "capacity_missed": 0,
    }

    for coin, streams in tape.items():
        trades = sorted(list(streams.get("TRADE") or []))
        rows = sorted(list(l2_history.get(str(coin).upper()) or []), key=lambda row: int(row.get("ts_ms") or 0))
        if len(trades) < 2 or not rows:
            continue
        shocks = lead_lag_shadow.detecter_chocs(trades, seuil_bps=float(shock_threshold_bps))
        raw_observations: list[dict[str, Any]] = []
        for shock_ns, raw_direction in shocks:
            coverage["shocks_seen"] += 1
            trigger_ms = int(shock_ns // 1_000_000)
            detection = _latest_at_or_before(rows, trigger_ms, max_age_ms=max_book_age_ms)
            if detection is None:
                coverage["missing_detection_book"] += 1
                continue
            entry_target = float(trigger_ms) + applied_latency_ms
            entry_selection = _book_for_execution(
                rows,
                entry_target,
                max_age_ms=min(max_book_age_ms, max_execution_observation_delay_ms),
                max_delay_ms=max_execution_observation_delay_ms,
            )
            if entry_selection is None:
                coverage["missing_entry_book"] += 1
                continue
            entry, entry_execution_ts_ms, entry_selection_kind = entry_selection
            exit_target = entry_execution_ts_ms + float(horizon_ms)
            exit_selection = _book_for_execution(
                rows,
                exit_target,
                max_age_ms=min(max_book_age_ms, max_execution_observation_delay_ms),
                max_delay_ms=max_execution_observation_delay_ms,
            )
            if exit_selection is None:
                coverage["missing_exit_book"] += 1
                continue
            exit_book, exit_execution_ts_ms, exit_selection_kind = exit_selection
            shock_direction = 1 if float(raw_direction) > 0 else -1
            primary_direction = shock_direction * int(direction_multiplier)
            event = _settle(
                coin=str(coin),
                direction=primary_direction,
                trigger_ts_ms=trigger_ms,
                detection_book=detection,
                entry_book=entry,
                exit_book=exit_book,
                entry_execution_ts_ms=entry_execution_ts_ms,
                exit_execution_ts_ms=exit_execution_ts_ms,
                notional_usd=float(notional_usd),
                fee_bps=float(fee_bps),
                measured_latency_ms=applied_latency_ms,
                entry_book_selection=entry_selection_kind,
                exit_book_selection=exit_selection_kind,
            )
            event["notional_usd"] = float(notional_usd)
            event["raw_shock_direction"] = int(shock_direction)
            event["direction_multiplier"] = int(direction_multiplier)
            event["direction_policy"] = primary_direction_policy
            # Reprice the opposite direction on the exact same causal books.
            # This is a diagnostic placebo only: it never participates in
            # admission, selection, segment PnL or promotion.
            direction_flip = _settle(
                coin=str(coin),
                direction=-int(event["direction"]),
                trigger_ts_ms=trigger_ms,
                detection_book=detection,
                entry_book=entry,
                exit_book=exit_book,
                entry_execution_ts_ms=entry_execution_ts_ms,
                exit_execution_ts_ms=exit_execution_ts_ms,
                notional_usd=float(notional_usd),
                fee_bps=float(fee_bps),
                measured_latency_ms=applied_latency_ms,
                entry_book_selection=entry_selection_kind,
                exit_book_selection=exit_selection_kind,
            )
            direction_flip["notional_usd"] = float(notional_usd)
            direction_flip["raw_shock_direction"] = int(shock_direction)
            direction_flip["direction_multiplier"] = -int(direction_multiplier)
            direction_flip["direction_policy"] = placebo_direction_policy
            direction_flip["diagnostic_only"] = True
            direction_flip["selection_eligible"] = False
            direction_flip["counterfactual_type"] = (
                "DIRECTION_FLIP_SAME_CAUSAL_EXECUTION_BOOKS"
            )
            event["direction_flip_pnl_usd"] = float(direction_flip["pnl_usd"])
            event["direction_flip_net_bps"] = float(direction_flip["net_bps"])
            event["direction_flip_gross_bps"] = float(direction_flip["gross_bps"])
            event["direction_flip_spread_bps"] = float(direction_flip["spread_bps"])
            raw_observations.append(event)
            direction_flip_diagnostics.append(direction_flip)
            coverage["observable"] += 1
            if event["full_fill"] is not True:
                coverage["capacity_missed"] += 1

        raw_observations.sort(key=lambda event: int(event["trigger_ts_ms"]))
        for index, event in enumerate(raw_observations):
            trigger = int(event["trigger_ts_ms"])
            prior = [
                previous
                for previous in raw_observations[:index]
                if int(previous["exit_ts_ms"]) <= trigger
                and previous.get("full_fill") is True
                and previous.get("economic_reconciled") is True
            ]
            expected = (
                statistics.fmean(float(previous["net_bps"]) for previous in prior)
                if len(prior) >= int(min_history)
                else None
            )
            event["expected_net_bps"] = None if expected is None else round(float(expected), 6)
            if expected is None:
                event["decision"] = "INSUFFICIENT_PRIOR_HISTORY"
            elif expected <= float(min_expected_net_bps):
                event["decision"] = "EXPECTED_NET_EDGE_NOT_POSITIVE"
            elif event.get("full_fill") is not True:
                event["decision"] = "TOP_CAPACITY_INSUFFICIENT"
            else:
                event["decision"] = "TRADE"
            candidates.append(event)

    candidates.sort(key=lambda event: (int(event["trigger_ts_ms"]), str(event["coin"])))
    decision_counts = dict(
        sorted(
            Counter(
                str(event.get("decision") or "UNKNOWN") for event in candidates
            ).items()
        )
    )
    raw_observation_diagnostics = _raw_observation_diagnostics(candidates)
    raw_observation_diagnostics.update(
        {
            "direction_multiplier": int(direction_multiplier),
            "direction_policy": primary_direction_policy,
        }
    )
    raw_direction_flip_diagnostics = _raw_observation_diagnostics(
        direction_flip_diagnostics
    )
    raw_direction_flip_diagnostics.update(
        {
            "counterfactual_type": "DIRECTION_FLIP_SAME_CAUSAL_EXECUTION_BOOKS",
            "direction_multiplier": -int(direction_multiplier),
            "direction_policy": placebo_direction_policy,
            "selection_eligible": False,
            "may_change_strategy": False,
        }
    )
    split_input = [
        {
            "ts_ms": int(event["trigger_ts_ms"]),
            "coin": event["coin"],
            "signe": event["direction"],
            "_event": event,
        }
        for event in candidates
    ]
    split = separer_par_episodes(split_input, fractions=(0.6, 0.2, 0.2))
    costs_measured = bool(latency_measured)
    segments = {
        label: _segment_summary(
            [row["_event"] for row in split[label]],
            costs_measured=costs_measured,
            equity=float(equity),
        )
        for label in ("IS", "OOS", "FORWARD")
    }

    traded = [event for event in candidates if event.get("decision") == "TRADE" and event.get("full_fill") is True]
    placebo_net = 0.0
    placebo_count = 0
    for event in traded:
        # Direction-flip placebo repriced on the opposite executable sides.
        placebo_net += float(event["direction_flip_pnl_usd"])
        placebo_count += 1

    in_sample = segments["IS"]
    metrics = {
        "is_net": in_sample["net"],
        "oos_net": segments["OOS"]["net"],
        "forward_net": segments["FORWARD"]["net"],
        "adverse_p95_net": min(segments["OOS"]["net"], segments["FORWARD"]["net"]),
        "capacity": sum(segment["fills"] for segment in segments.values()) * float(notional_usd),
        "reconciled": all(segment["LIQUIDATABLE_NET"] for segment in segments.values()),
    }
    enough = all(segment["closed_positions"] >= int(min_episodes) for segment in segments.values())
    verdict = "PROMU" if enough and metrics["reconciled"] and all(segment["net"] > 0 for segment in segments.values()) else "MORE_DATA"
    return {
        "segments": {label: {key: value for key, value in segment.items() if key != "ledger"} for label, segment in segments.items()},
        "metriques": metrics,
        "verdict": verdict,
        "placebo_net": round(placebo_net, 8),
        "placebo": {
            "net": round(placebo_net, 8),
            "sample_count": placebo_count,
            "type": "DIRECTION_FLIP_SAME_EXECUTION_TIMES",
        },
        "ledgers": {label: segment["ledger"] for label, segment in segments.items()},
        "ledger_is": segments["IS"]["ledger"],
        "signals": len(candidates),
        "decision_counts": decision_counts,
        "raw_observation_diagnostics": raw_observation_diagnostics,
        "raw_direction_flip_diagnostics": raw_direction_flip_diagnostics,
        "coverage": coverage,
        "latency_evidence": dict(latency_evidence),
        "costs_measured": costs_measured,
        "fee_bps": float(fee_bps),
        "fee_source": "FROZEN_CONSERVATIVE_TAKER_ROUND_TRIP",
        "direction_multiplier": int(direction_multiplier),
        "direction_policy": primary_direction_policy,
        "placebo_direction_policy": placebo_direction_policy,
        "slippage_rule": "ZERO_ONLY_WHEN_ENTRY_AND_EXIT_TOP_CAPACITY_COVER_FULL_NOTIONAL",
        "latency_rule": "P95_EMBEDDED_IN_DELAYED_ENTRY_PRICE_NO_DOUBLE_CHARGE",
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = ["load_runtime_latency_evidence", "replay_measured_lead_lag"]
