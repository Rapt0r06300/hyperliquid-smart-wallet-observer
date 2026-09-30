"""Predeclared TRAIN-only qualification for the next economic hypotheses.

This module does not place, simulate, or promote trades.  It answers a much
smaller question: does the immutable TRAIN segment contain enough reconciled
evidence to justify evaluating a materially new mechanism?  Validation, OOS,
and forward rows are deliberately ignored during selection.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from hl_observer.backtesting.cross_venue_certified import SOURCE_MODE as CERTIFIED_CROSS_SOURCE_MODE

from hl_observer.backtesting.queue_model import rejouer

SCHEMA_VERSION = "hypersmart.economic_hypotheses_v3.v1"
COPY_MECHANISM = "copy_vault_v3_train_leader_quality"
LEAD_MAKER_MECHANISM = "lead_lag_v3_eth_strong_shock_queue_maker"
CROSS_MECHANISM = "cross_venue_v3_atomic_coin_convergence"


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if result != result or abs(result) == float("inf"):
        return None
    return result


def _is_train(row: Mapping[str, Any]) -> bool:
    return str(row.get("walk_forward_segment") or row.get("segment") or "").lower() == "train"


def _economically_reconciled(row: Mapping[str, Any], *, net_key: str = "net_pnl_usd") -> bool:
    if row.get("economic_reconciliation_ok") is False:
        return False
    net = _number(row.get(net_key))
    gross = _number(row.get("gross_pnl_usd"))
    if net is None or gross is None:
        return False
    fees = _number(row.get("fees_usd")) or 0.0
    spread = _number(row.get("spread_cost_usd")) or 0.0
    slippage = _number(row.get("slippage_cost_usd")) or 0.0
    latency = _number(row.get("latency_cost_usd")) or 0.0
    rebate = _number(row.get("rebate_usd")) or 0.0
    expected = gross - fees - spread - slippage - latency + rebate
    tolerance = max(1e-8, abs(expected) * 1e-8)
    return abs(net - expected) <= tolerance


def _profit_factor(values: Sequence[float]) -> float | None:
    wins = sum(value for value in values if value > 0.0)
    losses = -sum(value for value in values if value < 0.0)
    if losses <= 1e-12:
        return None if wins <= 1e-12 else float("inf")
    return wins / losses


def _top_positive_share(values: Sequence[float]) -> float:
    positives = [value for value in values if value > 0.0]
    total = sum(positives)
    return max(positives, default=0.0) / total if total > 1e-12 else 1.0


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _base_result(mechanism: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    train_count = sum(1 for row in rows if _is_train(row))
    return {
        "schema_version": SCHEMA_VERSION,
        "mechanism": mechanism,
        "selection_scope": "TRAIN_ONLY",
        "train_rows_seen": train_count,
        "non_train_rows_ignored": len(rows) - train_count,
        "paper_read_only": True,
        "real_execution": False,
    }


def qualify_copy_vault_train_only(
    trades: Iterable[Mapping[str, Any]],
    *,
    minimum_trades: int = 8,
    minimum_profit_factor: float = 1.0,
    maximum_coin_trade_share: float = 0.65,
    maximum_positive_trade_share: float = 0.60,
) -> dict[str, Any]:
    """Select robust vault candidates using reconciled TRAIN rows only."""

    rows = [dict(row) for row in trades if isinstance(row, Mapping)]
    result = _base_result(COPY_MECHANISM, rows)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    invalid_train_rows = 0
    for row in rows:
        if not _is_train(row):
            continue
        vault = str(row.get("vault") or "").lower()
        if (
            not vault
            or row.get("liquidatable_net") is not True
            or not _economically_reconciled(row)
        ):
            invalid_train_rows += 1
            continue
        grouped[vault].append(row)

    candidates: list[dict[str, Any]] = []
    for vault, group in sorted(grouped.items()):
        net_values = [_number(row.get("net_pnl_usd")) or 0.0 for row in group]
        coin_counts: dict[str, int] = defaultdict(int)
        for row in group:
            coin_counts[str(row.get("coin") or "UNKNOWN").upper()] += 1
        largest_coin_share = max(coin_counts.values(), default=0) / max(1, len(group))
        pf = _profit_factor(net_values)
        top_win_share = _top_positive_share(net_values)
        reasons: list[str] = []
        if len(group) < minimum_trades:
            reasons.append("INSUFFICIENT_INDEPENDENT_TRAIN_TRADES")
        if sum(net_values) <= 0.0:
            reasons.append("TRAIN_NET_NOT_POSITIVE")
        if pf is None or pf <= minimum_profit_factor:
            reasons.append("TRAIN_PROFIT_FACTOR_NOT_ABOVE_ONE")
        if largest_coin_share > maximum_coin_trade_share:
            reasons.append("TRAIN_COIN_CONCENTRATION_TOO_HIGH")
        if top_win_share > maximum_positive_trade_share:
            reasons.append("TRAIN_ONE_BIG_WIN_RISK")
        candidates.append(
            {
                "vault": vault,
                "train_trades": len(group),
                "train_net_pnl_usd": round(sum(net_values), 8),
                "train_profit_factor": pf,
                "train_hit_rate": sum(value > 0.0 for value in net_values) / len(group),
                "distinct_coins": len(coin_counts),
                "largest_coin_trade_share": largest_coin_share,
                "top_positive_trade_share": top_win_share,
                "eligible": not reasons,
                "reasons": reasons,
            }
        )

    eligible = [row for row in candidates if row["eligible"]]
    selected = max(
        eligible,
        key=lambda row: (float(row["train_net_pnl_usd"]), int(row["train_trades"])),
        default=None,
    )
    enough_samples = any(row["train_trades"] >= minimum_trades for row in candidates)
    status = (
        "TRAIN_ELIGIBLE"
        if selected is not None
        else "KILL_TRAIN_NO_ROBUST_LEADER"
        if enough_samples
        else "MORE_DATA_INDEPENDENT_TRAIN_TRADES_REQUIRED"
    )
    evidence = {
        "minimum_trades": int(minimum_trades),
        "minimum_profit_factor": float(minimum_profit_factor),
        "maximum_coin_trade_share": float(maximum_coin_trade_share),
        "maximum_positive_trade_share": float(maximum_positive_trade_share),
        "selected_vault": selected.get("vault") if selected else None,
        "candidate_metrics": candidates,
    }
    return {
        **result,
        "status": status,
        "selection_eligible": selected is not None,
        "physical_freeze_allowed": selected is not None,
        "invalid_train_rows": invalid_train_rows,
        "selected": selected,
        "candidates": candidates,
        "selection_evidence_sha256": _stable_hash(evidence),
        "exact_next_evidence": (
            []
            if selected is not None
            else [
                "at least 8 independent reconciled causal TRAIN metaorders per vault",
                "positive TRAIN net and profit factor above one after all costs",
                "coin concentration <= 65% and no single winning trade > 60% of gains",
            ]
        ),
    }


def _queue_events(value: object) -> list[tuple[float, float]] | None:
    if not isinstance(value, list) or not value:
        return None
    events: list[tuple[float, float]] = []
    for item in value:
        if isinstance(item, Mapping):
            change = _number(item.get("book_size_change"))
            traded = _number(item.get("traded_qty_at_level"))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            change = _number(item[0])
            traded = _number(item[1])
        else:
            return None
        if change is None or traded is None or traded < 0.0:
            return None
        events.append((change, traded))
    return events


def qualify_lead_lag_queue_maker_train_only(
    report: Mapping[str, Any],
    *,
    minimum_trades: int = 8,
    required_coin: str = "ETH",
    minimum_abs_shock_bps: float = 20.0,
) -> dict[str, Any]:
    """Qualify a queue-aware maker hypothesis; touch-only fills never qualify."""

    raw_candidates = report.get("maker_queue_candidates")
    rows = (
        [dict(row) for row in raw_candidates if isinstance(row, Mapping)]
        if isinstance(raw_candidates, list)
        else []
    )
    result = _base_result(LEAD_MAKER_MECHANISM, rows)
    qualified: list[dict[str, Any]] = []
    missing_queue = 0
    missing_order_qty = 0
    rejected_predeclared = 0
    for row in rows:
        if not _is_train(row):
            continue
        if str(row.get("coin") or "").upper() != required_coin.upper():
            rejected_predeclared += 1
            continue
        shock = _number(row.get("lead_shock_bps"))
        if shock is None or abs(shock) < minimum_abs_shock_bps:
            rejected_predeclared += 1
            continue
        initial_ahead = _number(row.get("initial_qty_ahead"))
        paper_order_qty = _number(row.get("paper_order_qty"))
        events = _queue_events(row.get("queue_events"))
        if initial_ahead is None or initial_ahead < 0.0 or events is None:
            missing_queue += 1
            continue
        if paper_order_qty is None or paper_order_qty <= 0.0:
            missing_order_qty += 1
            continue
        # Consuming only the public quantity ahead means our order has merely
        # reached the front of the FIFO queue.  A full paper fill additionally
        # requires public volume equal to our own order quantity.
        required_qty = initial_ahead + paper_order_qty
        declared_required = _number(row.get("required_qty_for_full_fill"))
        if declared_required is not None and not abs(declared_required - required_qty) <= 1e-9:
            missing_queue += 1
            continue
        state = rejouer(required_qty, events)
        if not state.rempli:
            continue
        if (
            row.get("liquidatable_net") is not True
            or not _economically_reconciled(row)
        ):
            continue
        qualified.append(row)

    net_values = [_number(row.get("net_pnl_usd")) or 0.0 for row in qualified]
    pf = _profit_factor(net_values)
    replay_meta = report.get("maker_queue_replay")
    diagnostics = replay_meta if isinstance(replay_meta, Mapping) else {}
    latency_measured = diagnostics.get("latency_measured") is True
    shocks_seen = int(_number(diagnostics.get("strong_shocks_seen")) or 0)
    placebo_net = _number(diagnostics.get("train_placebo_net_pnl_usd"))
    train_net = sum(net_values)
    beats_placebo = placebo_net is not None and train_net > placebo_net + 1e-12
    train_economics_positive = bool(
        len(qualified) >= minimum_trades
        and train_net > 0.0
        and pf is not None
        and pf > 1.0
    )
    eligible = bool(train_economics_positive and latency_measured and beats_placebo)
    if eligible:
        status = "TRAIN_ELIGIBLE"
    elif missing_queue > 0 or missing_order_qty > 0:
        status = "MORE_DATA_QUEUE_EVIDENCE_REQUIRED"
    elif not diagnostics:
        status = "MAKER_REPLAY_EVIDENCE_REQUIRED"
    elif not latency_measured:
        status = "MEASURED_LATENCY_REQUIRED"
    elif shocks_seen == 0:
        status = "NO_PREDECLARED_STRONG_SHOCKS"
    elif not rows or len(qualified) < minimum_trades:
        status = "MORE_DATA_QUEUE_PROVEN_FILLS_REQUIRED"
    elif not train_economics_positive:
        status = "KILL_TRAIN_QUEUE_MAKER_NOT_PROFITABLE"
    elif placebo_net is None:
        status = "PLACEBO_EVIDENCE_REQUIRED"
    elif not beats_placebo:
        status = "KILL_TRAIN_PLACEBO_NOT_BEATEN"
    else:
        status = "KILL_TRAIN_QUEUE_MAKER_NOT_ELIGIBLE"
    evidence = {
        "required_coin": required_coin.upper(),
        "minimum_abs_shock_bps": float(minimum_abs_shock_bps),
        "minimum_trades": int(minimum_trades),
        "queue_proven_fills": len(qualified),
        "train_net_pnl_usd": round(train_net, 8),
        "train_profit_factor": pf,
        "train_placebo_net_pnl_usd": placebo_net,
        "beats_train_placebo": beats_placebo,
    }
    return {
        **result,
        "status": status,
        "selection_eligible": eligible,
        "physical_freeze_allowed": eligible,
        "required_coin": required_coin.upper(),
        "minimum_abs_shock_bps": float(minimum_abs_shock_bps),
        "candidate_rows_seen": len(rows),
        "queue_proven_fills": len(qualified),
        "missing_queue_evidence": missing_queue,
        "missing_paper_order_quantity": missing_order_qty,
        "predeclared_filter_rejections": rejected_predeclared,
        "latency_measured": latency_measured if diagnostics else None,
        "strong_shocks_seen": shocks_seen if diagnostics else None,
        "train_net_pnl_usd": round(train_net, 8),
        "train_profit_factor": pf,
        "train_placebo_net_pnl_usd": placebo_net,
        "beats_train_placebo": beats_placebo,
        "selection_evidence_sha256": _stable_hash(evidence),
        "exact_next_evidence": (
            []
            if eligible
            else [
                "ETH strong-shock candidates observed before any outcome is known",
                "multi-level L2 snapshot plus incremental trades at the passive price",
                "initial quantity ahead and queue replay proving each maker fill",
                "at least 8 reconciled queue-proven TRAIN fills profitable after costs",
                "independently replayed same-shock TRAIN placebo beaten",
            ]
        ),
    }


def qualify_cross_venue_train_only(
    trades: Iterable[Mapping[str, Any]],
    *,
    source_mode: str,
    minimum_trades: int = 8,
    minimum_profit_factor: float = 1.0,
    maximum_positive_trade_share: float = 0.60,
) -> dict[str, Any]:
    """Select atomic cross-venue coin hypotheses from TRAIN only."""

    rows = [dict(row) for row in trades if isinstance(row, Mapping)]
    result = _base_result(CROSS_MECHANISM, rows)
    atomic_source = source_mode == CERTIFIED_CROSS_SOURCE_MODE
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    invalid_train_rows = 0
    for row in rows:
        if not _is_train(row):
            continue
        if (
            not atomic_source
            or row.get("two_leg") is not True
            or row.get("LIQUIDATABLE_NET") is not True
            or (_number(row.get("depth_freshness_ms")) or float("inf")) > 3000.0
            or _number(row.get("basis_detect_bps")) is None
            or _number(row.get("basis_in_bps")) is None
            or _number(row.get("basis_out_bps")) is None
            or not _economically_reconciled_cross(row)
        ):
            invalid_train_rows += 1
            continue
        grouped[str(row.get("coin") or "UNKNOWN").upper()].append(row)

    candidates: list[dict[str, Any]] = []
    for coin, group in sorted(grouped.items()):
        values = [_number(row.get("net_usd")) or 0.0 for row in group]
        pf = _profit_factor(values)
        top_share = _top_positive_share(values)
        reasons: list[str] = []
        if len(group) < minimum_trades:
            reasons.append("INSUFFICIENT_ATOMIC_TRAIN_TRADES")
        if sum(values) <= 0.0:
            reasons.append("TRAIN_NET_NOT_POSITIVE")
        if pf is None or pf <= minimum_profit_factor:
            reasons.append("TRAIN_PROFIT_FACTOR_NOT_ABOVE_ONE")
        if top_share > maximum_positive_trade_share:
            reasons.append("TRAIN_ONE_BIG_WIN_RISK")
        candidates.append(
            {
                "coin": coin,
                "train_trades": len(group),
                "train_net_pnl_usd": round(sum(values), 8),
                "train_profit_factor": pf,
                "top_positive_trade_share": top_share,
                "eligible": not reasons,
                "reasons": reasons,
            }
        )
    eligible_candidates = [row for row in candidates if row["eligible"]]
    selected = max(
        eligible_candidates,
        key=lambda row: (float(row["train_net_pnl_usd"]), int(row["train_trades"])),
        default=None,
    )
    enough_samples = any(row["train_trades"] >= minimum_trades for row in candidates)
    status = (
        "TRAIN_ELIGIBLE"
        if selected is not None
        else "MORE_DATA_ATOMIC_FOUR_SIDE_BOOK_REQUIRED"
        if not atomic_source
        else "KILL_TRAIN_NO_ROBUST_CONVERGENCE_COIN"
        if enough_samples
        else "MORE_DATA_ATOMIC_TRAIN_TRADES_REQUIRED"
    )
    evidence = {
        "source_mode": source_mode,
        "minimum_trades": int(minimum_trades),
        "minimum_profit_factor": float(minimum_profit_factor),
        "maximum_positive_trade_share": float(maximum_positive_trade_share),
        "selected_coin": selected.get("coin") if selected else None,
        "candidate_metrics": candidates,
    }
    return {
        **result,
        "status": status,
        "selection_eligible": selected is not None,
        "physical_freeze_allowed": selected is not None,
        "source_mode": source_mode,
        "invalid_train_rows": invalid_train_rows,
        "selected": selected,
        "candidates": candidates,
        "selection_evidence_sha256": _stable_hash(evidence),
        "exact_next_evidence": (
            []
            if selected is not None
            else [
                "synchronized atomic HL and comparison-venue bid/ask with depth",
                "at least 8 reconciled liquidatable TRAIN round trips per mapped coin",
                "positive TRAIN net and profit factor above one after both legs and latency",
                "no single winning trade above 60% of TRAIN gains",
            ]
        ),
    }


def _economically_reconciled_cross(row: Mapping[str, Any]) -> bool:
    net = _number(row.get("net_usd"))
    net_bps = _number(row.get("net_bps"))
    notional = _number(row.get("notional_usd"))
    if net is None or net_bps is None or notional is None or notional <= 0.0:
        return False
    expected = notional * net_bps / 10000.0
    return abs(net - expected) <= max(1e-6, abs(expected) * 1e-5)


__all__ = [
    "COPY_MECHANISM",
    "CROSS_MECHANISM",
    "LEAD_MAKER_MECHANISM",
    "SCHEMA_VERSION",
    "qualify_copy_vault_train_only",
    "qualify_cross_venue_train_only",
    "qualify_lead_lag_queue_maker_train_only",
]
