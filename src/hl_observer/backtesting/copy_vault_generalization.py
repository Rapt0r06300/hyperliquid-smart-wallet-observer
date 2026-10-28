"""Fail-closed held-out-vault proof for executable Copy-Vault campaigns.

A vault is held out only if it never appears in any parseable executable evidence
before the OOS boundary. Strict campaign rows must also carry causal observation,
real cost decomposition, executable capacity and paper-only flags. Legacy minimal
rows remain readable for diagnostics but can never become an economic proof.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from typing import Any

from hl_observer.economics.numeric import (
    USD_RECONCILIATION_ABS_TOLERANCE,
    decimal_difference,
    decimal_sum,
    decimal_value,
    float_not_above,
    float_not_below,
)
from hl_observer.instrument_identity import preserve_native_instrument_symbol

ONE_BIG_WIN_SHARE_DECIMAL = Decimal("0.50")
ONE_BIG_WIN_SHARE = float(ONE_BIG_WIN_SHARE_DECIMAL)
VAULT_CONFLICT_WINDOW_MS = 60_000

_STRICT_SENTINELS = frozenset({
    "gross_pnl_usd", "fees_usd", "spread_cost_usd", "slippage_cost_usd",
    "latency_cost_usd", "entry_capacity_usd", "exit_capacity_usd",
    "causal_books_eligible", "causal_forward_eligible", "paper_read_only",
    "real_execution",
})
_COST_KEYS = ("fees_usd", "spread_cost_usd", "slippage_cost_usd", "latency_cost_usd")


def _net_bps(net: Decimal, notional: Decimal) -> float | None:
    if notional <= 0:
        return None
    with localcontext() as context:
        context.prec = 80
        context.rounding = ROUND_FLOOR
        value = net / notional * Decimal(10_000)
    return float_not_above(value)


def _ratio_floor(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator <= 0:
        return None
    with localcontext() as context:
        context.prec = 80
        context.rounding = ROUND_FLOOR
        return numerator / denominator


def _ratio_ceiling(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator <= 0:
        return None
    with localcontext() as context:
        context.prec = 80
        context.rounding = ROUND_CEILING
        return numerator / denominator


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _strict_candidate(raw: Mapping[str, Any]) -> bool:
    return any(key in raw for key in _STRICT_SENTINELS)


def _strict_expected_net(raw: Mapping[str, Any]) -> Decimal | None:
    gross = decimal_value(raw.get("gross_pnl_usd"))
    costs = [decimal_value(raw.get(key)) for key in _COST_KEYS]
    if gross is None or any(value is None for value in costs):
        return None
    return decimal_sum(
        [gross, *(value.copy_negate() for value in costs if value is not None)]
    )


def _strict_issues(raw: Mapping[str, Any], *, net: Decimal, notional: Decimal) -> list[str]:
    issues: list[str] = []
    if raw.get("paper_read_only") is not True or raw.get("real_execution") is not False:
        issues.append("NOT_PAPER_READ_ONLY")
    if raw.get("causal_books_eligible") is not True:
        issues.append("NON_CAUSAL_BOOKS")
    if raw.get("causal_forward_eligible") is not True:
        issues.append("NON_CAUSAL_SIGNAL_OR_BOOK")
    gross = decimal_value(raw.get("gross_pnl_usd"))
    costs = {key: decimal_value(raw.get(key)) for key in _COST_KEYS}
    if gross is None:
        issues.append("GROSS_PNL_UNMEASURED")
    for key, value in costs.items():
        if value is None:
            issues.append(f"COST_UNMEASURED:{key}")
        elif value < 0:
            issues.append(f"NEGATIVE_COST:{key}")
    if gross is not None and all(value is not None for value in costs.values()):
        expected = _strict_expected_net(raw)
        discrepancy = decimal_difference(expected, net)
        if (
            discrepancy is None
            or discrepancy.copy_abs() > USD_RECONCILIATION_ABS_TOLERANCE
        ):
            issues.append("ECONOMIC_RECONCILIATION_FAILED")
    entry_capacity = decimal_value(raw.get("entry_capacity_usd"))
    exit_capacity = decimal_value(raw.get("exit_capacity_usd"))
    if entry_capacity is None or exit_capacity is None:
        issues.append("CAPACITY_UNMEASURED")
    elif min(entry_capacity, exit_capacity) < notional:
        issues.append("INSUFFICIENT_EXECUTABLE_CAPACITY")
    for key in ("reference_lag_ms", "entry_target_lag_ms", "exit_target_lag_ms", "observed_latency_ms"):
        value = _finite_float(raw.get(key))
        if value is None:
            issues.append(f"LATENCY_UNMEASURED:{key}")
        elif value < 0:
            issues.append(f"NEGATIVE_LATENCY:{key}")
    try:
        direction = int(raw.get("direction"))
    except (TypeError, ValueError, OverflowError):
        direction = 0
    if direction not in (-1, 1):
        issues.append("INVALID_DIRECTION")
    if not str(raw.get("coin") or "").strip():
        issues.append("COIN_MISSING")
    return list(dict.fromkeys(issues))


def _empty(*, strict_mode: bool, candidate_count: int = 0, rejected: Counter[str] | None = None) -> dict[str, Any]:
    reasons = dict(sorted((rejected or Counter()).items()))
    return {
        "sample_count": 0, "candidate_sample_count": int(candidate_count),
        "rejected_candidate_count": sum(reasons.values()), "rejection_reasons": reasons,
        "duplicate_trade_ids": reasons.get("DUPLICATE_TRADE_ID", 0), "net_bps": None,
        "diagnostic_net_bps": None, "vaults_held_out": [], "heldout_vault_count": 0,
        "heldout_profit_vault_count": 0, "profitable_vault_ratio": None,
        "min_heldout_vault_net_pnl_usd": None, "net_pnl_usd": None,
        "net_pnl_usd_exact_decimal": None, "notional_usd": None,
        "notional_usd_exact_decimal": None,
        "trade_ids_count": 0, "trade_ids_sha256": hashlib.sha256(b"").hexdigest(),
        "max_drawdown_usd": None, "max_drawdown_usd_exact_decimal": None,
        "positive_trade_ratio": None,
        "largest_positive_trade_share": None,
        "largest_positive_trade_share_upper_bound_decimal": None,
        "largest_positive_vault_share": None,
        "largest_positive_vault_share_upper_bound_decimal": None,
        "one_big_win_dependency": None, "one_big_win_share_threshold": ONE_BIG_WIN_SHARE,
        "one_big_win_share_threshold_exact_decimal": format(ONE_BIG_WIN_SHARE_DECIMAL, "f"),
        "total_fees_usd": None, "total_spread_cost_usd": None,
        "total_slippage_cost_usd": None, "total_latency_cost_usd": None,
        "max_observed_latency_ms": None, "min_capacity_headroom_ratio": None,
        "execution_regimes": {}, "vault_conflict_pairs": 0,
        "conflict_window_ms": VAULT_CONFLICT_WINDOW_MS, "economic_claim_eligible": False,
        "proof_mode": "STRICT_EXECUTABLE" if strict_mode else "LEGACY_COMPAT_DIAGNOSTIC",
        "definition": "vault_absent_from_all_pre_oos_observed_evidence_then_measured_oos_forward_only",
        "role": "SECONDARY_ROBUSTNESS_REQUIRED_FOR_ECONOMIC_CLAIM",
    }


def derive_heldout_vault_generalization(trades: Iterable[Mapping[str, Any]], *, oos_start_ms: int | None) -> dict[str, Any] | None:
    """Build a held-out proof; strict executable evidence fails closed.

    Vault identity is compared case-insensitively. Human-readable symbolic labels
    keep their source spelling, while 0x-address-like identifiers are rendered in
    canonical lowercase so proof output cannot vary with address casing.
    """
    if oos_start_ms is None:
        return None
    try:
        boundary = int(oos_start_ms)
    except (TypeError, ValueError, OverflowError):
        return None
    if boundary <= 0:
        return None
    parsed: list[dict[str, Any]] = []
    strict_mode = False
    for raw in trades:
        if not isinstance(raw, Mapping):
            continue
        vault_raw = str(raw.get("vault") or "").strip()
        vault = vault_raw.casefold()
        vault_display = vault if vault.startswith("0x") else vault_raw
        coin = preserve_native_instrument_symbol(raw.get("coin"))
        try:
            ts_ms = int(raw.get("signal_ts_ms") or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        net = decimal_value(raw.get("net_pnl_usd"))
        notional = decimal_value(raw.get("notional_usd"))
        trade_id = str(raw.get("trade_id") or "").strip()
        if not vault or ts_ms <= 0 or net is None or notional is None or notional <= 0 or raw.get("liquidatable_net") is not True or len(trade_id) != 64:
            continue
        strict = _strict_candidate(raw)
        strict_mode = strict_mode or strict
        strict_issues = _strict_issues(raw, net=net, notional=notional) if strict else []
        expected_net = _strict_expected_net(raw) if strict else None
        if strict and not strict_issues and expected_net is not None:
            # A reconciliation tolerance can admit a row, but it cannot create PnL.
            net = min(net, expected_net)
        parsed.append({**dict(raw), "vault": vault, "_vault_display": vault_display,
                       "coin": coin, "signal_ts_ms": ts_ms,
                       "net_pnl_usd": net, "notional_usd": notional, "trade_id": trade_id,
                       "_strict": strict,
                       "_strict_issues": strict_issues})
    pre_oos_vaults = {row["vault"] for row in parsed if int(row["signal_ts_ms"]) < boundary}
    candidates = [row for row in parsed if int(row["signal_ts_ms"]) >= boundary and row["vault"] not in pre_oos_vaults]
    if not candidates:
        return _empty(strict_mode=strict_mode)
    rejected: Counter[str] = Counter()
    accepted: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in sorted(candidates, key=lambda item: (int(item["signal_ts_ms"]), str(item["trade_id"]))):
        if strict_mode and not row["_strict"]:
            rejected["MIXED_LEGACY_ROW_IN_STRICT_PROOF"] += 1
            continue
        issues = list(row["_strict_issues"])
        if issues:
            for issue in issues:
                rejected[issue] += 1
            continue
        trade_id = str(row["trade_id"])
        if trade_id in seen_ids:
            rejected["DUPLICATE_TRADE_ID"] += 1
            continue
        seen_ids.add(trade_id)
        accepted.append(row)
    if not accepted:
        return _empty(strict_mode=strict_mode, candidate_count=len(candidates), rejected=rejected)
    by_vault: dict[str, dict[str, Any]] = {}
    positive_trades = 0
    positive_trade_values: list[Decimal] = []
    strict_cost_values = {key: [] for key in _COST_KEYS}
    latency_values: list[float] = []
    headroom_values: list[float] = []
    regimes: Counter[str] = Counter()
    equity = peak = max_drawdown = Decimal(0)
    net_values: list[Decimal] = []
    notional_values: list[Decimal] = []
    for row in accepted:
        vault = str(row["vault"])
        net = row["net_pnl_usd"]
        notional = row["notional_usd"]
        if not isinstance(net, Decimal) or not isinstance(notional, Decimal):
            return _empty(strict_mode=strict_mode, candidate_count=len(candidates), rejected=Counter({"INVALID_MONETARY_VALUE": 1}))
        bucket = by_vault.setdefault(
            vault,
            {"display_vault": str(row["_vault_display"]), "sample_count": 0,
             "net_values": [], "notional_values": []},
        )
        bucket["sample_count"] = int(bucket["sample_count"]) + 1
        bucket["net_values"].append(net)
        bucket["notional_values"].append(notional)
        net_values.append(net)
        notional_values.append(notional)
        equity_value = decimal_sum((equity, net))
        if equity_value is None:
            return _empty(strict_mode=strict_mode, candidate_count=len(candidates), rejected=Counter({"AGGREGATE_UNREPRESENTABLE": 1}))
        equity = equity_value
        peak = max(peak, equity)
        drawdown_value = decimal_difference(peak, equity)
        if drawdown_value is None:
            return _empty(strict_mode=strict_mode, candidate_count=len(candidates), rejected=Counter({"AGGREGATE_UNREPRESENTABLE": 1}))
        max_drawdown = max(max_drawdown, drawdown_value)
        if net > 0:
            positive_trades += 1
            positive_trade_values.append(net)
        if strict_mode:
            for key in _COST_KEYS:
                cost = decimal_value(row.get(key))
                if cost is None:
                    return _empty(strict_mode=True, candidate_count=len(candidates), rejected=Counter({f"COST_UNMEASURED:{key}": 1}))
                strict_cost_values[key].append(cost)
            latency_values.append(float(row["observed_latency_ms"]))
            entry_capacity = decimal_value(row.get("entry_capacity_usd"))
            exit_capacity = decimal_value(row.get("exit_capacity_usd"))
            if entry_capacity is None or exit_capacity is None:
                return _empty(strict_mode=True, candidate_count=len(candidates), rejected=Counter({"CAPACITY_UNMEASURED": 1}))
            capacity = min(entry_capacity, exit_capacity)
            headroom = _ratio_floor(capacity, notional)
            if headroom is None:
                return _empty(strict_mode=True, candidate_count=len(candidates), rejected=Counter({"CAPACITY_UNMEASURED": 1}))
            headroom_float = float_not_above(headroom)
            if headroom_float is None:
                return _empty(strict_mode=True, candidate_count=len(candidates), rejected=Counter({"AGGREGATE_UNREPRESENTABLE": 1}))
            headroom_values.append(headroom_float)
            costs = {key: decimal_value(row.get(key)) for key in _COST_KEYS}
            if any(value is None for value in costs.values()):
                return _empty(strict_mode=True, candidate_count=len(candidates), rejected=Counter({"COST_UNMEASURED": 1}))
            dominant_key = max(_COST_KEYS, key=lambda key: (costs[key], key))
            regimes[f"COST_DOMINANT_{dominant_key.removesuffix('_usd').upper()}"] += 1
    total_net = decimal_sum(net_values)
    total_notional = decimal_sum(notional_values)
    positive_pnl = decimal_sum(positive_trade_values)
    strict_cost_totals = {key: decimal_sum(values) for key, values in strict_cost_values.items()}
    if total_net is None or total_notional is None or positive_pnl is None or any(value is None for value in strict_cost_totals.values()):
        return _empty(strict_mode=strict_mode, candidate_count=len(candidates), rejected=Counter({"AGGREGATE_UNREPRESENTABLE": 1}))
    vault_exact: dict[str, tuple[Decimal, Decimal]] = {}
    vault_rows: list[dict[str, Any]] = []
    positive_vault_values: list[Decimal] = []
    for vault in sorted(by_vault):
        bucket = by_vault[vault]
        net = decimal_sum(bucket["net_values"])
        notional = decimal_sum(bucket["notional_values"])
        if net is None or notional is None:
            return _empty(strict_mode=strict_mode, candidate_count=len(candidates), rejected=Counter({"AGGREGATE_UNREPRESENTABLE": 1}))
        vault_exact[vault] = (net, notional)
        if net > 0:
            positive_vault_values.append(net)
        net_float = float_not_above(net)
        notional_float = float_not_below(notional)
        net_bps = _net_bps(net, notional)
        if net_float is None or notional_float is None:
            return _empty(strict_mode=strict_mode, candidate_count=len(candidates), rejected=Counter({"AGGREGATE_UNREPRESENTABLE": 1}))
        vault_rows.append({"vault": str(bucket["display_vault"]), "sample_count": int(bucket["sample_count"]),
                           "net_pnl_usd": net_float, "net_pnl_usd_exact_decimal": str(net),
                           "notional_usd": notional_float, "notional_usd_exact_decimal": str(notional),
                           "net_bps": net_bps})
    conflicts = 0
    by_coin: dict[str, list[dict[str, Any]]] = {}
    for row in accepted:
        if str(row.get("coin") or ""):
            by_coin.setdefault(str(row["coin"]), []).append(row)
    for rows in by_coin.values():
        rows.sort(key=lambda item: int(item["signal_ts_ms"]))
        for index, left in enumerate(rows):
            for right in rows[index + 1:]:
                gap = int(right["signal_ts_ms"]) - int(left["signal_ts_ms"])
                if gap > VAULT_CONFLICT_WINDOW_MS:
                    break
                if left["vault"] != right["vault"] and int(left.get("direction") or 0) == -int(right.get("direction") or 0):
                    conflicts += 1
    unique_ids = sorted(str(row["trade_id"]) for row in accepted)
    diagnostic_net_bps = _net_bps(total_net, total_notional)
    total_net_float = float_not_above(total_net)
    total_notional_float = float_not_below(total_notional)
    max_drawdown_float = float_not_below(max_drawdown)
    if total_net_float is None or total_notional_float is None or max_drawdown_float is None:
        return _empty(strict_mode=strict_mode, candidate_count=len(candidates), rejected=Counter({"AGGREGATE_UNREPRESENTABLE": 1}))
    economic_claim_eligible = bool(
        strict_mode and accepted and not rejected and all(row["_strict"] for row in accepted)
        and diagnostic_net_bps is not None
    )
    largest_trade_ratio = (
        _ratio_ceiling(max(positive_trade_values), positive_pnl)
        if positive_pnl > 0 and positive_trade_values else None
    )
    largest_trade_share = float(largest_trade_ratio) if largest_trade_ratio is not None else None
    positive_vault_total = decimal_sum(positive_vault_values)
    largest_vault_ratio = (
        _ratio_ceiling(max(positive_vault_values), positive_vault_total)
        if positive_vault_total is not None and positive_vault_total > 0 and positive_vault_values else None
    )
    largest_vault_share = float(largest_vault_ratio) if largest_vault_ratio is not None else None
    min_vault_net = min(net for net, _ in vault_exact.values())
    min_vault_net_float = float_not_above(min_vault_net)
    if min_vault_net_float is None:
        return _empty(strict_mode=strict_mode, candidate_count=len(candidates), rejected=Counter({"AGGREGATE_UNREPRESENTABLE": 1}))
    cost_outputs: dict[str, tuple[float | None, str | None]] = {}
    for key, value in strict_cost_totals.items():
        if not isinstance(value, Decimal):
            return _empty(strict_mode=strict_mode, candidate_count=len(candidates), rejected=Counter({"AGGREGATE_UNREPRESENTABLE": 1}))
        cost_outputs[key] = (float_not_below(value), str(value))
    if strict_mode and any(value[0] is None for value in cost_outputs.values()):
        return _empty(strict_mode=True, candidate_count=len(candidates), rejected=Counter({"AGGREGATE_UNREPRESENTABLE": 1}))
    rejection_reasons = dict(sorted(rejected.items()))
    return {
        "sample_count": len(accepted), "candidate_sample_count": len(candidates),
        "rejected_candidate_count": sum(rejected.values()), "rejection_reasons": rejection_reasons,
        "duplicate_trade_ids": rejection_reasons.get("DUPLICATE_TRADE_ID", 0),
        "net_bps": diagnostic_net_bps if (economic_claim_eligible or not strict_mode) else None,
        "diagnostic_net_bps": diagnostic_net_bps, "vaults_held_out": [row["vault"] for row in vault_rows],
        "heldout_vault_count": len(vault_rows),
        "heldout_profit_vault_count": sum(1 for net, _ in vault_exact.values() if net > 0),
        "profitable_vault_ratio": float(
            _ratio_floor(
                Decimal(sum(1 for net, _ in vault_exact.values() if net > 0)),
                Decimal(len(vault_exact)),
            )
        ),
        "min_heldout_vault_net_pnl_usd": min_vault_net_float,
        "net_pnl_usd": total_net_float, "net_pnl_usd_exact_decimal": str(total_net),
        "notional_usd": total_notional_float, "notional_usd_exact_decimal": str(total_notional),
        "trade_ids_count": len(unique_ids), "trade_ids_sha256": hashlib.sha256("\n".join(unique_ids).encode("utf-8")).hexdigest(),
        "max_drawdown_usd": max_drawdown_float, "max_drawdown_usd_exact_decimal": str(max_drawdown),
        "positive_trade_ratio": float(_ratio_floor(Decimal(positive_trades), Decimal(len(accepted)))),
        "largest_positive_trade_share": round(largest_trade_share, 8) if largest_trade_share is not None else None,
        "largest_positive_trade_share_upper_bound_decimal": (
            format(largest_trade_ratio, "f") if largest_trade_ratio is not None else None
        ),
        "largest_positive_vault_share": round(largest_vault_share, 8) if largest_vault_share is not None else None,
        "largest_positive_vault_share_upper_bound_decimal": (
            format(largest_vault_ratio, "f") if largest_vault_ratio is not None else None
        ),
        "one_big_win_dependency": (
            largest_trade_ratio > ONE_BIG_WIN_SHARE_DECIMAL
            if largest_trade_ratio is not None else None
        ),
        "one_big_win_share_threshold": ONE_BIG_WIN_SHARE,
        "one_big_win_share_threshold_exact_decimal": format(ONE_BIG_WIN_SHARE_DECIMAL, "f"),
        "total_fees_usd": cost_outputs["fees_usd"][0] if strict_mode else None,
        "total_fees_usd_exact_decimal": cost_outputs["fees_usd"][1] if strict_mode else None,
        "total_spread_cost_usd": cost_outputs["spread_cost_usd"][0] if strict_mode else None,
        "total_spread_cost_usd_exact_decimal": cost_outputs["spread_cost_usd"][1] if strict_mode else None,
        "total_slippage_cost_usd": cost_outputs["slippage_cost_usd"][0] if strict_mode else None,
        "total_slippage_cost_usd_exact_decimal": cost_outputs["slippage_cost_usd"][1] if strict_mode else None,
        "total_latency_cost_usd": cost_outputs["latency_cost_usd"][0] if strict_mode else None,
        "total_latency_cost_usd_exact_decimal": cost_outputs["latency_cost_usd"][1] if strict_mode else None,
        "max_observed_latency_ms": max(latency_values) if latency_values else None,
        "min_capacity_headroom_ratio": min(headroom_values) if headroom_values else None,
        "execution_regimes": dict(sorted(regimes.items())), "vault_conflict_pairs": conflicts,
        "conflict_window_ms": VAULT_CONFLICT_WINDOW_MS, "per_vault": vault_rows,
        "economic_claim_eligible": economic_claim_eligible,
        "proof_mode": "STRICT_EXECUTABLE" if strict_mode else "LEGACY_COMPAT_DIAGNOSTIC",
        "definition": "vault_absent_from_all_pre_oos_observed_evidence_then_measured_oos_forward_only",
        "role": "SECONDARY_ROBUSTNESS_REQUIRED_FOR_ECONOMIC_CLAIM",
    }


__all__ = [
    "ONE_BIG_WIN_SHARE",
    "ONE_BIG_WIN_SHARE_DECIMAL",
    "VAULT_CONFLICT_WINDOW_MS",
    "derive_heldout_vault_generalization",
]
