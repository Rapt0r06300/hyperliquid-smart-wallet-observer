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
from typing import Any

ONE_BIG_WIN_SHARE = 0.50
VAULT_CONFLICT_WINDOW_MS = 60_000

_STRICT_SENTINELS = frozenset({
    "gross_pnl_usd", "fees_usd", "spread_cost_usd", "slippage_cost_usd",
    "latency_cost_usd", "entry_capacity_usd", "exit_capacity_usd",
    "causal_books_eligible", "causal_forward_eligible", "paper_read_only",
    "real_execution",
})
_COST_KEYS = ("fees_usd", "spread_cost_usd", "slippage_cost_usd", "latency_cost_usd")


def _finite_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _strict_candidate(raw: Mapping[str, Any]) -> bool:
    return any(key in raw for key in _STRICT_SENTINELS)


def _strict_issues(raw: Mapping[str, Any], *, net: float, notional: float) -> list[str]:
    issues: list[str] = []
    if raw.get("paper_read_only") is not True or raw.get("real_execution") is not False:
        issues.append("NOT_PAPER_READ_ONLY")
    if raw.get("causal_books_eligible") is not True:
        issues.append("NON_CAUSAL_BOOKS")
    if raw.get("causal_forward_eligible") is not True:
        issues.append("NON_CAUSAL_SIGNAL_OR_BOOK")
    gross = _finite_float(raw.get("gross_pnl_usd"))
    costs = {key: _finite_float(raw.get(key)) for key in _COST_KEYS}
    if gross is None:
        issues.append("GROSS_PNL_UNMEASURED")
    for key, value in costs.items():
        if value is None:
            issues.append(f"COST_UNMEASURED:{key}")
        elif value < 0:
            issues.append(f"NEGATIVE_COST:{key}")
    if gross is not None and all(value is not None for value in costs.values()):
        expected = gross - sum(float(value) for value in costs.values())
        if not math.isclose(expected, net, abs_tol=1e-6):
            issues.append("ECONOMIC_RECONCILIATION_FAILED")
    entry_capacity = _finite_float(raw.get("entry_capacity_usd"))
    exit_capacity = _finite_float(raw.get("exit_capacity_usd"))
    if entry_capacity is None or exit_capacity is None:
        issues.append("CAPACITY_UNMEASURED")
    elif min(entry_capacity, exit_capacity) + 1e-9 < notional:
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
        "min_heldout_vault_net_pnl_usd": None, "net_pnl_usd": 0.0, "notional_usd": 0.0,
        "trade_ids_count": 0, "trade_ids_sha256": hashlib.sha256(b"").hexdigest(),
        "max_drawdown_usd": 0.0, "positive_trade_ratio": None,
        "largest_positive_trade_share": None, "largest_positive_vault_share": None,
        "one_big_win_dependency": None, "one_big_win_share_threshold": ONE_BIG_WIN_SHARE,
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

    Vault identity is compared case-insensitively, while the original spelling is
    retained for human-readable proof output. This prevents ``A`` and ``a`` from
    becoming two different vaults without corrupting checksummed/display labels.
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
        vault_display = str(raw.get("vault") or "").strip()
        vault = vault_display.casefold()
        coin = str(raw.get("coin") or "").strip().upper()
        try:
            ts_ms = int(raw.get("signal_ts_ms") or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        net = _finite_float(raw.get("net_pnl_usd"))
        notional = _finite_float(raw.get("notional_usd"))
        trade_id = str(raw.get("trade_id") or "").strip()
        if not vault or ts_ms <= 0 or net is None or notional is None or notional <= 0 or raw.get("liquidatable_net") is not True or len(trade_id) != 64:
            continue
        strict = _strict_candidate(raw)
        strict_mode = strict_mode or strict
        parsed.append({**dict(raw), "vault": vault, "_vault_display": vault_display,
                       "coin": coin, "signal_ts_ms": ts_ms,
                       "net_pnl_usd": net, "notional_usd": notional, "trade_id": trade_id,
                       "_strict": strict,
                       "_strict_issues": _strict_issues(raw, net=net, notional=notional) if strict else []})
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
    by_vault: dict[str, dict[str, float | int | str]] = {}
    total_net = total_notional = positive_pnl = 0.0
    positive_trades = 0
    positive_trade_values: list[float] = []
    strict_cost_totals = {key: 0.0 for key in _COST_KEYS}
    latency_values: list[float] = []
    headroom_values: list[float] = []
    regimes: Counter[str] = Counter()
    equity = peak = max_drawdown = 0.0
    for row in accepted:
        vault, net, notional = str(row["vault"]), float(row["net_pnl_usd"]), float(row["notional_usd"])
        bucket = by_vault.setdefault(
            vault,
            {"display_vault": str(row["_vault_display"]), "sample_count": 0,
             "net_pnl_usd": 0.0, "notional_usd": 0.0},
        )
        bucket["sample_count"] = int(bucket["sample_count"]) + 1
        bucket["net_pnl_usd"] = float(bucket["net_pnl_usd"]) + net
        bucket["notional_usd"] = float(bucket["notional_usd"]) + notional
        total_net += net; total_notional += notional
        equity += net; peak = max(peak, equity); max_drawdown = max(max_drawdown, peak - equity)
        if net > 0:
            positive_pnl += net; positive_trades += 1; positive_trade_values.append(net)
        if strict_mode:
            for key in _COST_KEYS:
                strict_cost_totals[key] += float(row[key])
            latency_values.append(float(row["observed_latency_ms"]))
            headroom_values.append(min(float(row["entry_capacity_usd"]), float(row["exit_capacity_usd"])) / notional)
            costs = {"FEES": float(row["fees_usd"]), "SPREAD": float(row["spread_cost_usd"]),
                     "SLIPPAGE": float(row["slippage_cost_usd"]), "LATENCY": float(row["latency_cost_usd"])}
            dominant = max(costs, key=lambda key: (costs[key], key)); regimes[f"COST_DOMINANT_{dominant}"] += 1
    vault_rows: list[dict[str, Any]] = []; positive_vault_values: list[float] = []
    for vault in sorted(by_vault):
        bucket = by_vault[vault]; notional = float(bucket["notional_usd"]); net = float(bucket["net_pnl_usd"])
        if net > 0: positive_vault_values.append(net)
        vault_rows.append({"vault": str(bucket["display_vault"]), "sample_count": int(bucket["sample_count"]),
                           "net_pnl_usd": round(net, 8), "notional_usd": round(notional, 8),
                           "net_bps": round(net / notional * 10_000.0, 8) if notional > 0 else None})
    conflicts = 0; by_coin: dict[str, list[dict[str, Any]]] = {}
    for row in accepted:
        if str(row.get("coin") or ""): by_coin.setdefault(str(row["coin"]), []).append(row)
    for rows in by_coin.values():
        rows.sort(key=lambda item: int(item["signal_ts_ms"]))
        for index, left in enumerate(rows):
            for right in rows[index + 1:]:
                gap = int(right["signal_ts_ms"]) - int(left["signal_ts_ms"])
                if gap > VAULT_CONFLICT_WINDOW_MS: break
                if left["vault"] != right["vault"] and int(left.get("direction") or 0) == -int(right.get("direction") or 0): conflicts += 1
    unique_ids = sorted(str(row["trade_id"]) for row in accepted)
    diagnostic_net_bps = round(total_net / total_notional * 10_000.0, 8) if total_notional > 0 else None
    economic_claim_eligible = bool(strict_mode and accepted and not rejected and all(row["_strict"] for row in accepted))
    largest_trade_share = max(positive_trade_values) / positive_pnl if positive_pnl > 0 and positive_trade_values else None
    positive_vault_total = sum(positive_vault_values)
    largest_vault_share = max(positive_vault_values) / positive_vault_total if positive_vault_total > 0 and positive_vault_values else None
    rejection_reasons = dict(sorted(rejected.items()))
    return {
        "sample_count": len(accepted), "candidate_sample_count": len(candidates),
        "rejected_candidate_count": sum(rejected.values()), "rejection_reasons": rejection_reasons,
        "duplicate_trade_ids": rejection_reasons.get("DUPLICATE_TRADE_ID", 0),
        "net_bps": diagnostic_net_bps if (economic_claim_eligible or not strict_mode) else None,
        "diagnostic_net_bps": diagnostic_net_bps, "vaults_held_out": [row["vault"] for row in vault_rows],
        "heldout_vault_count": len(vault_rows),
        "heldout_profit_vault_count": sum(1 for row in vault_rows if float(row["net_pnl_usd"]) > 0),
        "profitable_vault_ratio": round(sum(1 for row in vault_rows if float(row["net_pnl_usd"]) > 0) / len(vault_rows), 8),
        "min_heldout_vault_net_pnl_usd": round(min(float(row["net_pnl_usd"]) for row in vault_rows), 8),
        "net_pnl_usd": round(total_net, 8), "notional_usd": round(total_notional, 8),
        "trade_ids_count": len(unique_ids), "trade_ids_sha256": hashlib.sha256("\n".join(unique_ids).encode("utf-8")).hexdigest(),
        "max_drawdown_usd": round(max_drawdown, 8), "positive_trade_ratio": round(positive_trades / len(accepted), 8),
        "largest_positive_trade_share": round(largest_trade_share, 8) if largest_trade_share is not None else None,
        "largest_positive_vault_share": round(largest_vault_share, 8) if largest_vault_share is not None else None,
        "one_big_win_dependency": bool(largest_trade_share > ONE_BIG_WIN_SHARE) if largest_trade_share is not None else None,
        "one_big_win_share_threshold": ONE_BIG_WIN_SHARE,
        "total_fees_usd": round(strict_cost_totals["fees_usd"], 8) if strict_mode else None,
        "total_spread_cost_usd": round(strict_cost_totals["spread_cost_usd"], 8) if strict_mode else None,
        "total_slippage_cost_usd": round(strict_cost_totals["slippage_cost_usd"], 8) if strict_mode else None,
        "total_latency_cost_usd": round(strict_cost_totals["latency_cost_usd"], 8) if strict_mode else None,
        "max_observed_latency_ms": max(latency_values) if latency_values else None,
        "min_capacity_headroom_ratio": round(min(headroom_values), 8) if headroom_values else None,
        "execution_regimes": dict(sorted(regimes.items())), "vault_conflict_pairs": conflicts,
        "conflict_window_ms": VAULT_CONFLICT_WINDOW_MS, "per_vault": vault_rows,
        "economic_claim_eligible": economic_claim_eligible,
        "proof_mode": "STRICT_EXECUTABLE" if strict_mode else "LEGACY_COMPAT_DIAGNOSTIC",
        "definition": "vault_absent_from_all_pre_oos_observed_evidence_then_measured_oos_forward_only",
        "role": "SECONDARY_ROBUSTNESS_REQUIRED_FOR_ECONOMIC_CLAIM",
    }


__all__ = ["ONE_BIG_WIN_SHARE", "VAULT_CONFLICT_WINDOW_MS", "derive_heldout_vault_generalization"]
