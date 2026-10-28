"""Strict, shared proof contract for per-family paper economic objectives.

Displayed/modelled PnL is kept separate from PnL eligible for an economic claim.
Missing costs, identities, forward proof, paper guards or Cross-Venue atomic
provenance fail closed.
"""
from __future__ import annotations

import hashlib
import math
import statistics
import time
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal, localcontext
from typing import Any

from hl_observer.backtesting.copy_vault_protocol import CHECKPOINT_INTEGRITY_SCHEMA
from hl_observer.backtesting.cross_venue_certified import (
    FOUR_FILL_CONTRACT_VERSION,
)
from hl_observer.backtesting.cross_venue_certified import (
    SOURCE_MODE as CROSS_CERTIFIED_SOURCE_MODE,
)
from hl_observer.economics.numeric import (
    USD_RECONCILIATION_ABS_TOLERANCE,
    decimal_difference,
    decimal_sum,
    decimal_value,
    float_not_above,
    float_not_below,
)
from hl_observer.strategies.active_scope import strategy_can_materialize

TARGET_NET_USD = 5.0
TARGET_NET_USD_PER_DAY = 5.0
MIN_PROOF_DAYS = 2
STARTING_CAPITAL_USD = 200.0
ECONOMIC_CONTRACT_VERSION = "alina.economic_objective.200usd-5usd-day.v1"
EVIDENCE_LEVEL_THRESHOLDS = (
    ("PROVEN", 30, 150),
    ("PROVISIONAL", 14, 75),
    ("PROMISING", 7, 30),
    ("EARLY_EVIDENCE", 2, 10),
)
COPY_HELDOUT_MIN_N = 20
CANONICAL_FAMILIES = ("copy_vault",)
_ALIASES = {
    "copy-vault": "copy_vault", "copy_vault": "copy_vault",
    "lead-lag": "lead_lag", "lead_lag": "lead_lag",
    "arbitrage": "cross_venue_dislocation_v2",
    "cross_venue_dislocation": "cross_venue_dislocation_v2",
    "cross_venue_dislocation_v2": "cross_venue_dislocation_v2",
}
_ECONOMIC_KEYS = ("gross_pnl_usd", "fees_usd", "spread_cost_usd", "slippage_cost_usd", "latency_cost_usd", "net_pnl_usd")
_COST_KEYS = ("fees_usd", "spread_cost_usd", "slippage_cost_usd", "latency_cost_usd")


def _integer_timestamp(value: object) -> int | None:
    if isinstance(value, float) and abs(value) > 2**53:
        # Such a float cannot preserve every integer timestamp unit (notably ns).
        return None
    exact = decimal_value(value)
    if exact is None or exact != exact.to_integral_value():
        return None
    return int(exact)


def canonical_family(value: object) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    return _ALIASES.get(normalized, normalized)


def evaluate_daily_net(
    trades: Iterable[Mapping[str, Any]],
    *,
    target_net_usd_per_day: float = TARGET_NET_USD_PER_DAY,
    as_of_ms: int | float | None = None,
    complete_utc_days_only: bool = True,
) -> dict[str, Any]:
    """Aggregate closed-trade net PnL over completed UTC days, fail closed."""

    target_decimal = decimal_value(target_net_usd_per_day)
    if target_decimal is None:
        raise ValueError("target_net_usd_per_day must be finite")
    target = float(target_decimal)
    if not math.isfinite(target):
        raise ValueError("target_net_usd_per_day must fit a finite JSON number")
    evaluated_at = _number(time.time() * 1000 if as_of_ms is None else as_of_ms)
    if evaluated_at is None:
        raise ValueError("as_of_ms must be finite")
    day_ms = 86_400_000
    completed_cutoff_exclusive_ms = int(evaluated_at // day_ms) * day_ms
    daily: dict[str, list[Decimal]] = {}
    counts: dict[str, int] = {}
    regimes: set[str] = set()
    excluded_incomplete_trade_count = 0
    excluded_incomplete_days: set[str] = set()
    missing_trade_timestamps = 0
    missing_trade_net = 0
    observed_trades = 0
    for trade in trades:
        observed_trades += 1
        if not isinstance(trade, Mapping):
            missing_trade_timestamps += 1
            missing_trade_net += 1
            continue
        timestamp_ms = next(
            (
                value
                for key in ("exit_ts_ms", "ts_out", "close_ts_ms", "timestamp_ms")
                for value in [_integer_timestamp(trade.get(key))]
                if value is not None
            ),
            None,
        )
        if timestamp_ms is None:
            timestamp_ns = next(
                (
                    value
                    for key in (
                        "exit_ts_ns",
                        "ts_out_ns",
                        "close_ts_ns",
                        "timestamp_ns",
                    )
                    for value in [_integer_timestamp(trade.get(key))]
                    if value is not None
                ),
                None,
            )
            if timestamp_ns is not None:
                timestamp_ms = timestamp_ns // 1_000_000
        net = next(
            (
                value
                for key in ("net_pnl_usd", "net_usd", "net")
                for value in [decimal_value(trade.get(key))]
                if value is not None
            ),
            None,
        )
        if timestamp_ms is None:
            missing_trade_timestamps += 1
        if net is None:
            missing_trade_net += 1
        if timestamp_ms is None or net is None:
            continue
        day_number = timestamp_ms // day_ms
        try:
            day = (
                datetime(1970, 1, 1, tzinfo=timezone.utc)
                + timedelta(days=day_number)
            ).date().isoformat()
        except (OverflowError, ValueError):
            missing_trade_timestamps += 1
            continue
        if complete_utc_days_only and timestamp_ms >= completed_cutoff_exclusive_ms:
            excluded_incomplete_trade_count += 1
            excluded_incomplete_days.add(day)
            continue
        daily.setdefault(day, []).append(net)
        counts[day] = counts.get(day, 0) + 1
        regime = str(trade.get("regime") or trade.get("market_regime") or "").strip()
        if regime:
            regimes.add(regime)

    daily_totals = {day: decimal_sum(parts) for day, parts in daily.items()}
    days = []
    unrepresentable_daily_net_count = 0
    for day, exact_value in sorted(daily_totals.items()):
        output_value = float_not_above(exact_value) if exact_value is not None else None
        if output_value is None:
            unrepresentable_daily_net_count += 1
        days.append(
            {
                "date_utc": day,
                "net_pnl_usd": output_value,
                "net_pnl_usd_exact_decimal": (
                    format(exact_value, "f") if exact_value is not None else None
                ),
                "trade_count": counts[day],
                "at_or_above_target": bool(
                    exact_value is not None
                    and output_value is not None
                    and exact_value >= target_decimal
                ),
            }
        )
    values = (
        [float(value) for value in daily_totals.values() if value is not None]
        if not unrepresentable_daily_net_count
        else []
    )
    eligible_trade_count = sum(counts.values())
    evidence_level = "MORE_DATA"
    for level, minimum_days, minimum_trades in EVIDENCE_LEVEL_THRESHOLDS:
        if (
            missing_trade_timestamps == 0
            and missing_trade_net == 0
            and len(daily_totals) >= minimum_days
            and eligible_trade_count >= minimum_trades
            and unrepresentable_daily_net_count == 0
        ):
            evidence_level = level
            break
    positive_total = decimal_sum(
        value for value in daily_totals.values() if value is not None and value > 0
    )
    negative_total = decimal_sum(
        value.copy_abs()
        for value in daily_totals.values()
        if value is not None and value < 0
    )
    with localcontext() as context:
        context.prec = 80
        context.rounding = ROUND_FLOOR
        profit_factor_decimal = (
            positive_total / negative_total
            if positive_total is not None
            and negative_total is not None
            and negative_total > 0
            else None
        )
    profit_factor = (
        float_not_above(profit_factor_decimal)
        if profit_factor_decimal is not None
        else None
    )
    mean = statistics.fmean(values) if values else None
    stdev = statistics.stdev(values) if len(values) >= 2 else None
    downside = [min(value, 0.0) for value in values]
    downside_deviation = (
        math.sqrt(statistics.fmean(value * value for value in downside))
        if downside
        else None
    )
    running = Decimal(0)
    peak = Decimal(0)
    max_drawdown = Decimal(0)
    for value in daily_totals.values():
        if value is None:
            continue
        next_running = decimal_sum((running, value))
        if next_running is None:
            unrepresentable_daily_net_count += 1
            continue
        running = next_running
        peak = max(peak, running)
        drawdown = decimal_difference(peak, running)
        if drawdown is None:
            unrepresentable_daily_net_count += 1
            continue
        max_drawdown = max(max_drawdown, drawdown)

    def quantile(fraction: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        position = (len(ordered) - 1) * fraction
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return ordered[lower]
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    total_net_exact = (
        decimal_sum(daily_totals.values())
        if daily_totals and not unrepresentable_daily_net_count
        else None
    )
    mean_net_exact_ratio = (
        {
            "numerator_decimal": format(total_net_exact, "f"),
            "denominator": len(daily_totals),
        }
        if total_net_exact is not None and daily_totals
        else None
    )
    mean_net_conservative_decimal = None
    if total_net_exact is not None and daily_totals:
        with localcontext() as context:
            context.prec = 80
            context.rounding = ROUND_FLOOR
            mean_net_conservative_decimal = total_net_exact / Decimal(len(daily_totals))
    return {
        "schema_version": "hypersmart.daily_net_evidence.v2",
        "economic_contract_version": ECONOMIC_CONTRACT_VERSION,
        "target_net_usd_per_day": float(target),
        "target_net_usd_per_day_exact_decimal": format(target_decimal, "f"),
        "minimum_required_days": MIN_PROOF_DAYS,
        "evaluated_at_ms": int(evaluated_at),
        "completed_cutoff_exclusive_ms": completed_cutoff_exclusive_ms,
        "complete_utc_days_only": bool(complete_utc_days_only),
        "excluded_incomplete_trade_count": excluded_incomplete_trade_count,
        "excluded_incomplete_days_utc": sorted(excluded_incomplete_days),
        "sample_count": len(daily_totals),
        "observed_trade_count": observed_trades,
        "eligible_trade_count": eligible_trade_count,
        "observed_regime_count": len(regimes),
        "observed_regimes": sorted(regimes),
        "evidence_level": evidence_level,
        "missing_trade_timestamps": missing_trade_timestamps,
        "missing_trade_net": missing_trade_net,
        "unrepresentable_daily_net_count": unrepresentable_daily_net_count,
        "days": days,
        "total_net_pnl_usd": (
            float_not_above(total_net_exact) if total_net_exact is not None else None
        ),
        "total_net_pnl_usd_exact_decimal": (
            format(total_net_exact, "f") if total_net_exact is not None else None
        ),
        "mean_daily_net_pnl_usd": (
            float_not_above(mean_net_conservative_decimal)
            if mean_net_conservative_decimal is not None
            else None
        ),
        "mean_daily_net_pnl_usd_exact_ratio": mean_net_exact_ratio,
        "median_daily_net_pnl_usd": round(statistics.median(values), 8) if values else None,
        "p10_daily_net_pnl_usd": round(quantile(0.10), 8) if values else None,
        "p25_daily_net_pnl_usd": round(quantile(0.25), 8) if values else None,
        "p75_daily_net_pnl_usd": round(quantile(0.75), 8) if values else None,
        "p90_daily_net_pnl_usd": round(quantile(0.90), 8) if values else None,
        "min_daily_net_pnl_usd": (
            float_not_above(min(daily_totals.values()))
            if daily_totals and not unrepresentable_daily_net_count
            else None
        ),
        "max_daily_net_pnl_usd": (
            float_not_above(max(daily_totals.values()))
            if daily_totals and not unrepresentable_daily_net_count
            else None
        ),
        "max_drawdown_usd": (
            float_not_below(max_drawdown)
            if daily_totals and not unrepresentable_daily_net_count
            else None
        ),
        "profit_factor": profit_factor,
        "profit_factor_exact_decimal": (
            format(profit_factor_decimal, "f")
            if profit_factor_decimal is not None
            else None
        ),
        "sharpe": round(mean / stdev, 8) if mean is not None and stdev not in (None, 0.0) else None,
        "sortino": round(mean / downside_deviation, 8) if mean is not None and downside_deviation not in (None, 0.0) else None,
        "all_days_at_or_above_target": bool(
            daily_totals
            and len(daily_totals) >= MIN_PROOF_DAYS
            and missing_trade_timestamps == 0
            and missing_trade_net == 0
            and unrepresentable_daily_net_count == 0
            and all(value is not None for value in daily_totals.values())
            and min(daily_totals.values()) >= target_decimal
        ),
    }


def _number(value: object) -> float | None:
    exact = decimal_value(value)
    if exact is None:
        return None
    try:
        result = float(exact)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _segment_economics(segment: Mapping[str, Any] | None, *, label: str, issues: list[str]) -> dict[str, Any] | None:
    if not isinstance(segment, Mapping):
        return None
    metrics = {key: decimal_value(segment.get(key)) for key in _ECONOMIC_KEYS}
    missing = [key for key, value in metrics.items() if value is None]
    issues.extend(f"{label}_UNMEASURED:{key}" for key in missing)
    for key in _COST_KEYS:
        if metrics[key] is not None and metrics[key] < 0:
            issues.append(f"{label}_NEGATIVE_COST:{key}")
    reconciled = False
    if not missing:
        expected = decimal_sum(
            (
                metrics["gross_pnl_usd"],
                *(metrics[key].copy_negate() for key in _COST_KEYS),
            )
        )
        discrepancy = decimal_difference(expected, metrics["net_pnl_usd"])
        reconciled = bool(
            expected is not None
            and discrepancy is not None
            and discrepancy.copy_abs() <= USD_RECONCILIATION_ABS_TOLERANCE
        )
        if not reconciled:
            issues.append(f"{label}_ECONOMIC_RECONCILIATION_FAILED")
        elif expected is not None:
            # A tolerated discrepancy is uncertainty, never extra credited PnL.
            metrics["net_pnl_usd"] = min(metrics["net_pnl_usd"], expected)
    count = _number(segment.get("sample_count"))
    trade_count = _number(segment.get("trade_ids_count"))
    duplicates = _number(segment.get("duplicate_trade_ids"))
    trade_hash = str(segment.get("trade_ids_sha256") or "")
    liquidatable = segment.get("liquidatable_net")
    if liquidatable is None:
        liquidatable = segment.get("LIQUIDATABLE_NET")
    if liquidatable is not True:
        issues.append(f"{label}_NOT_LIQUIDATABLE_NET")
    if duplicates != 0:
        issues.append(f"{label}_DUPLICATE_TRADE_IDENTITIES")
    if count is None or count <= 0 or trade_count != count or len(trade_hash) != 64:
        issues.append(f"{label}_TRADE_ID_PROOF_INCOMPLETE")
    complete = bool(not missing and reconciled and count is not None and count > 0 and trade_count == count and duplicates == 0 and len(trade_hash) == 64 and liquidatable is True)
    if not complete:
        return None
    return {**metrics, "sample_count": int(count), "trade_ids_count": int(trade_count), "trade_ids_sha256": trade_hash}


def _validate_cross_provenance(evidence: Mapping[str, Any], issues: list[str]) -> None:
    period = evidence.get("period")
    period = period if isinstance(period, Mapping) else {}
    meta = period.get("collection_meta")
    meta = meta if isinstance(meta, Mapping) else {}
    if meta.get("source_mode") != CROSS_CERTIFIED_SOURCE_MODE:
        issues.append("CROSS_VENUE_CERTIFIED_ATOMIC_SOURCE_MISSING")
    if int(_number(meta.get("certified_snapshots")) or 0) <= 0:
        issues.append("CROSS_VENUE_CERTIFIED_SNAPSHOT_PROOF_MISSING")
    if meta.get("mapping_verified") is not True:
        issues.append("CROSS_VENUE_MAPPING_PROOF_MISSING")
    if meta.get("skew_verified") is not True:
        issues.append("CROSS_VENUE_SKEW_PROOF_MISSING")
    if meta.get("four_fill_contract_version") != FOUR_FILL_CONTRACT_VERSION:
        issues.append("CROSS_VENUE_FOUR_FILL_CONTRACT_MISSING")


def _validate_copy_checkpoint_integrity(
    evidence: Mapping[str, Any], issues: list[str]
) -> None:
    integrity = evidence.get("copy_checkpoint_integrity")
    oos = evidence.get("oos")
    forward = evidence.get("forward")
    expected_proof_count = (
        int(_number(oos.get("sample_count")) or 0)
        + int(_number(forward.get("sample_count")) or 0)
        if isinstance(oos, Mapping) and isinstance(forward, Mapping)
        else 0
    )
    clean = bool(
        isinstance(integrity, Mapping)
        and integrity.get("schema_version")
        == CHECKPOINT_INTEGRITY_SCHEMA
        and integrity.get("receipt_valid") is True
        and integrity.get("writer_role") == "BOUND_WRITER"
        and bool(str(integrity.get("writer_run_id") or "").strip())
        and int(_number(integrity.get("clean_epoch_ms")) or 0) > 0
        and _number(integrity.get("duplicate_checkpoint_ids")) == 0
        and _number(integrity.get("quarantined_checkpoint_metaorders")) == 0
        and expected_proof_count > 0
        and _number(integrity.get("proof_trade_count")) == expected_proof_count
        and _number(integrity.get("expected_proof_trade_count"))
        == expected_proof_count
        and integrity.get("all_proof_trades_exact_checkpoint_bound") is True
        and integrity.get("all_proof_trades_same_writer_run") is True
        and integrity.get("all_proof_trades_post_clean_epoch") is True
    )
    if not clean:
        issues.append("COPY_CHECKPOINT_INTEGRITY_NOT_CLEAN")


def evaluate_objective(evidence: Mapping[str, Any], *, target_net_usd: float = TARGET_NET_USD) -> dict[str, Any]:
    issues: list[str] = []
    family = canonical_family(evidence.get("family"))
    if family not in CANONICAL_FAMILIES or not strategy_can_materialize(family):
        issues.extend(("DISABLED_BY_SCOPE", "NON_CANONICAL_OR_INACTIVE_FAMILY"))
    if evidence.get("paper_read_only") is not True or evidence.get("real_execution") is not False:
        issues.append("NOT_PAPER_READ_ONLY")
    capital = _number(evidence.get("starting_capital_usd"))
    if capital != STARTING_CAPITAL_USD:
        issues.append("INVALID_STARTING_CAPITAL")
    if evidence.get("parameters_frozen") is not True:
        issues.append("PARAMETERS_NOT_FROZEN_BEFORE_EVALUATION")
    opened = _number(evidence.get("opened_positions"))
    closed = _number(evidence.get("closed_positions"))
    if opened is None or closed is None or opened <= 0 or opened != closed:
        issues.append("POSITIONS_NOT_FULLY_OPENED_AND_CLOSED")
    if family == "cross_venue_dislocation_v2":
        if evidence.get("all_positions_two_leg_closed") is not True:
            issues.append("CROSS_VENUE_TWO_LEG_CLOSE_PROOF_MISSING")
        _validate_cross_provenance(evidence, issues)
    if family == "copy_vault":
        _validate_copy_checkpoint_integrity(evidence, issues)
        generalisation = evidence.get("vault_generalization")
        if not isinstance(generalisation, Mapping):
            issues.append("COPY_HELDOUT_VAULT_PROOF_MISSING")
        else:
            heldout_n = _number(generalisation.get("sample_count"))
            heldout_net_bps = _number(generalisation.get("net_bps"))
            if heldout_n is None or heldout_n < COPY_HELDOUT_MIN_N:
                issues.append("COPY_HELDOUT_VAULT_SAMPLE_TOO_SMALL")
            if heldout_net_bps is None:
                issues.append("COPY_HELDOUT_VAULT_NET_MISSING")
            elif heldout_net_bps <= 0:
                issues.append("COPY_HELDOUT_VAULT_NET_NOT_POSITIVE")
    metrics = {key: decimal_value(evidence.get(key)) for key in _ECONOMIC_KEYS}
    missing = [key for key, value in metrics.items() if value is None]
    issues.extend(f"UNMEASURED:{key}" for key in missing)
    for key in _COST_KEYS:
        if metrics[key] is not None and metrics[key] < 0:
            issues.append(f"NEGATIVE_COST:{key}")
    if not missing:
        expected = decimal_sum(
            (
                metrics["gross_pnl_usd"],
                *(metrics[key].copy_negate() for key in _COST_KEYS),
            )
        )
        discrepancy = decimal_difference(expected, metrics["net_pnl_usd"])
        if (
            expected is None
            or discrepancy is None
            or discrepancy.copy_abs() > USD_RECONCILIATION_ABS_TOLERANCE
        ):
            issues.append("ECONOMIC_RECONCILIATION_FAILED")
    liquidatable = evidence.get("liquidatable_net")
    if liquidatable is None:
        liquidatable = evidence.get("LIQUIDATABLE_NET")
    if liquidatable is not True:
        issues.append("NOT_LIQUIDATABLE_NET")
    duplicates = _number(evidence.get("duplicate_trade_ids"))
    trade_count = _number(evidence.get("trade_ids_count"))
    trade_hash = str(evidence.get("trade_ids_sha256") or "")
    if duplicates != 0:
        issues.append("DUPLICATE_TRADE_IDENTITIES")
    if closed is None or trade_count != closed or len(trade_hash) != 64:
        issues.append("TRADE_ID_PROOF_INCOMPLETE")
    oos = evidence.get("oos")
    forward = evidence.get("forward")
    placebos = evidence.get("placebos")
    oos_net = decimal_value(oos.get("net_pnl_usd")) if isinstance(oos, Mapping) else None
    oos_count = _number(oos.get("sample_count")) if isinstance(oos, Mapping) else None
    forward_net = decimal_value(forward.get("net_pnl_usd")) if isinstance(forward, Mapping) else None
    forward_count = _number(forward.get("sample_count")) if isinstance(forward, Mapping) else None
    oos_economics = _segment_economics(oos if isinstance(oos, Mapping) else None, label="OOS", issues=issues)
    forward_economics = _segment_economics(forward if isinstance(forward, Mapping) else None, label="FORWARD", issues=issues)
    if oos_economics is not None and forward_economics is not None and oos_economics["trade_ids_sha256"] == forward_economics["trade_ids_sha256"]:
        issues.append("OOS_FORWARD_TRADE_IDENTITY_COLLISION")
    if not isinstance(oos, Mapping) or oos_net is None:
        issues.append("OOS_PROOF_MISSING")
    elif oos_count is None or oos_count <= 0:
        issues.append("OOS_SAMPLE_MISSING")
    elif oos_net <= 0:
        issues.append("OOS_NET_NOT_POSITIVE")
    elif oos.get("no_lookahead") is not True:
        issues.append("OOS_NO_LOOKAHEAD_PROOF_MISSING")
    if not isinstance(forward, Mapping) or forward_net is None:
        issues.append("FORWARD_POST_FREEZE_PROOF_MISSING")
    elif forward_count is None or forward_count <= 0:
        issues.append("FORWARD_SAMPLE_MISSING")
    elif forward_net <= 0:
        issues.append("FORWARD_NET_NOT_POSITIVE")
    elif forward.get("post_freeze") is not True:
        issues.append("FORWARD_NOT_PROVEN_POST_FREEZE")
    if not isinstance(placebos, Mapping) or placebos.get("beaten") is not True:
        issues.append("PLACEBO_NOT_BEATEN")
    daily_evidence = evidence.get("daily_evidence")
    daily_target_required = evidence.get("daily_target_required") is True
    if daily_target_required:
        if not isinstance(daily_evidence, Mapping):
            issues.append("DAILY_NET_PROOF_MISSING")
        else:
            daily_sample_count = _number(daily_evidence.get("sample_count")) or 0
            daily_min_net = decimal_value(daily_evidence.get("min_daily_net_pnl_usd"))
            daily_target = decimal_value(daily_evidence.get("target_net_usd_per_day"))
            unrepresentable_daily_count = _number(
                daily_evidence.get("unrepresentable_daily_net_count", 0)
            )
            if daily_sample_count < MIN_PROOF_DAYS:
                issues.append("DAILY_NET_PROOF_TOO_SHORT")
            if daily_evidence.get("complete_utc_days_only") is not True:
                issues.append("DAILY_NET_PROOF_HAS_INCOMPLETE_DAY")
            if not (
                daily_evidence.get("schema_version")
                in {"hypersmart.daily_net_evidence.v1", "hypersmart.daily_net_evidence.v2"}
                and daily_target == Decimal(str(TARGET_NET_USD_PER_DAY))
                and daily_evidence.get("complete_utc_days_only") is True
                and daily_sample_count > 0
                and _number(daily_evidence.get("missing_trade_timestamps")) == 0
                and _number(daily_evidence.get("missing_trade_net")) == 0
                and unrepresentable_daily_count == 0
                and daily_min_net is not None
                and daily_min_net >= Decimal(str(TARGET_NET_USD_PER_DAY))
                and daily_evidence.get("all_days_at_or_above_target") is True
            ):
                issues.append("DAILY_NET_TARGET_NOT_REACHED")
    proof_economics = None
    proof_net_decimal = None
    if oos_economics is not None and forward_economics is not None:
        exact_totals = {
            key: decimal_sum((oos_economics[key], forward_economics[key]))
            for key in _ECONOMIC_KEYS
            if key != "net_pnl_usd"
        }
        exact_costs = [exact_totals.get(key) for key in _COST_KEYS]
        exact_gross = exact_totals.get("gross_pnl_usd")
        exact_reported_net = decimal_sum(
            (oos_economics["net_pnl_usd"], forward_economics["net_pnl_usd"])
        )
        exact_reconciled_net = (
            decimal_sum(
                (
                    exact_gross,
                    *(value.copy_negate() for value in exact_costs if value is not None),
                )
            )
            if exact_gross is not None and all(value is not None for value in exact_costs)
            else None
        )
        if exact_reported_net is not None and exact_reconciled_net is not None:
            proof_net_decimal = min(exact_reported_net, exact_reconciled_net)
        if (
            proof_net_decimal is None
            or exact_gross is None
            or any(value is None for value in exact_costs)
        ):
            issues.append("PROOF_ECONOMICS_UNREPRESENTABLE")
        else:
            proof_economics = {
                "gross_pnl_usd": float_not_above(exact_gross),
                "fees_usd": float_not_below(exact_totals["fees_usd"]),
                "spread_cost_usd": float_not_below(exact_totals["spread_cost_usd"]),
                "slippage_cost_usd": float_not_below(exact_totals["slippage_cost_usd"]),
                "latency_cost_usd": float_not_below(exact_totals["latency_cost_usd"]),
                "net_pnl_usd": float_not_above(proof_net_decimal),
                "sample_count": int(oos_economics["sample_count"])
                + int(forward_economics["sample_count"]),
            }
            if any(
                proof_economics[key] is None
                for key in _ECONOMIC_KEYS
            ):
                proof_economics = None
                proof_net_decimal = None
                issues.append("PROOF_ECONOMICS_UNREPRESENTABLE")
            else:
                proof_economics["trade_ids_count"] = proof_economics["sample_count"]
                proof_economics["trade_ids_sha256"] = hashlib.sha256((str(oos_economics["trade_ids_sha256"]) + "\n" + str(forward_economics["trade_ids_sha256"])).encode("utf-8")).hexdigest()
    target_decimal = decimal_value(target_net_usd)
    if target_decimal is None:
        issues.append("INVALID_TARGET_NET_USD")
    proof_net = float_not_above(proof_net_decimal) if proof_net_decimal is not None else None
    if proof_net_decimal is None or proof_net is None or target_decimal is None or proof_net_decimal < target_decimal:
        issues.append("TARGET_NET_USD_NOT_REACHED")
    unique_issues = list(dict.fromkeys(issues))
    return {"family": family, "target_net_usd": float(target_decimal) if target_decimal is not None else None, "target_net_usd_per_day": TARGET_NET_USD_PER_DAY, "daily_target_required": daily_target_required, "daily_evidence": dict(daily_evidence) if isinstance(daily_evidence, Mapping) else None, "copy_checkpoint_integrity": dict(evidence["copy_checkpoint_integrity"]) if isinstance(evidence.get("copy_checkpoint_integrity"), Mapping) else None, "proof_economics": proof_economics, "proof_net_pnl_usd": proof_net, "eligible_net_pnl_usd": proof_net if not unique_issues else None, "objective_status": "ATTEINT" if not unique_issues else "NON_ATTEINT", "objective_reasons": unique_issues}


__all__ = ["CANONICAL_FAMILIES", "COPY_HELDOUT_MIN_N", "ECONOMIC_CONTRACT_VERSION", "EVIDENCE_LEVEL_THRESHOLDS", "MIN_PROOF_DAYS", "STARTING_CAPITAL_USD", "TARGET_NET_USD", "TARGET_NET_USD_PER_DAY", "canonical_family", "evaluate_daily_net", "evaluate_objective"]
