"""Copy-Vault vNext TRAIN-only causal consensus research.

The killed simple whitelist is not reused.  A candidate is admitted only when
multiple distinct recorded vault addresses independently point to the same coin
and direction inside a predeclared causal lookback window.  Admission reads no
PnL and never consults validation/OOS/forward.  Only already executable,
liquidatable and economically reconciled TRAIN rows are scored afterwards.

Distinct addresses are not claimed to be distinct human entities.  The report
states this limitation explicitly.  PAPER/READ-ONLY; selection merely creates a
freeze candidate and cannot certify the family.
"""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.train_statistics import stable_hash, summarize_train_rows

SCHEMA_VERSION = "hypersmart.copy_vault_vnext_train.v1"
MECHANISM = "copy_vault_vnext_causal_multiwallet_consensus"
CONSENSUS_WINDOWS_MS = (30_000, 120_000, 300_000)
MIN_DISTINCT_WALLETS = (2, 3)
MIN_TRAIN_TRADES = 8
MIN_DISTINCT_DAYS = 3
MAX_COIN_TRADE_SHARE = 0.65
MAX_VAULT_TRADE_SHARE = 0.50
MAX_TOP_POSITIVE_SHARE = 0.60
FAMILY_ALPHA = 0.05


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _reconciled(row: Mapping[str, Any]) -> bool:
    if row.get("economic_reconciliation_ok") is False:
        return False
    net = _number(row.get("net_pnl_usd"))
    gross = _number(row.get("gross_pnl_usd"))
    if net is None or gross is None:
        return False
    fees = _number(row.get("fees_usd")) or 0.0
    spread = _number(row.get("spread_cost_usd")) or 0.0
    slippage = _number(row.get("slippage_cost_usd")) or 0.0
    latency = _number(row.get("latency_cost_usd")) or 0.0
    expected = gross - fees - spread - slippage - latency
    return math.isclose(expected, net, abs_tol=max(1e-8, abs(expected) * 1e-8))


def _train_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    trades = report.get("trades")
    if not isinstance(trades, list):
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in trades:
        if not isinstance(raw, Mapping):
            continue
        segment = str(raw.get("walk_forward_segment") or raw.get("segment") or "").lower()
        if segment != "train":
            continue
        trade_id = str(raw.get("trade_id") or "")
        vault = str(raw.get("vault") or "").strip().lower()
        coin = str(raw.get("coin") or "").strip().upper()
        try:
            direction = int(raw.get("direction") or 0)
            signal_ts_ms = int(raw.get("signal_ts_ms") or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        if (
            not trade_id
            or trade_id in seen
            or not vault
            or not coin
            or direction not in (-1, 1)
            or signal_ts_ms <= 0
            or raw.get("liquidatable_net") is not True
            or not _reconciled(raw)
        ):
            continue
        seen.add(trade_id)
        result.append(dict(raw))
    result.sort(key=lambda row: (int(row["signal_ts_ms"]), str(row["trade_id"])))
    return result


def admit_consensus_train_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    window_ms: int,
    minimum_distinct_wallets: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Apply a prior-only consensus gate; PnL is never read for admission."""

    ordered = sorted(
        [dict(row) for row in rows],
        key=lambda row: (int(row.get("signal_ts_ms") or 0), str(row.get("trade_id") or "")),
    )
    admitted: list[dict[str, Any]] = []
    reasons = Counter()
    for index, row in enumerate(ordered):
        timestamp = int(row.get("signal_ts_ms") or 0)
        coin = str(row.get("coin") or "").upper()
        direction = int(row.get("direction") or 0)
        current_vault = str(row.get("vault") or "").lower()
        prior_vaults: set[str] = set()
        for previous in reversed(ordered[:index]):
            previous_ts = int(previous.get("signal_ts_ms") or 0)
            age = timestamp - previous_ts
            if age > int(window_ms):
                break
            if age <= 0:
                continue
            if (
                str(previous.get("coin") or "").upper() == coin
                and int(previous.get("direction") or 0) == direction
            ):
                vault = str(previous.get("vault") or "").lower()
                if vault and vault != current_vault:
                    prior_vaults.add(vault)
        distinct_addresses = len(prior_vaults | {current_vault}) if current_vault else len(prior_vaults)
        if distinct_addresses < int(minimum_distinct_wallets):
            reasons["INSUFFICIENT_PRIOR_DISTINCT_WALLET_CONSENSUS"] += 1
            continue
        admitted.append(
            {
                **row,
                "consensus_window_ms": int(window_ms),
                "minimum_distinct_wallets": int(minimum_distinct_wallets),
                "prior_supporting_wallet_addresses": sorted(prior_vaults),
                "distinct_wallet_addresses_at_signal": distinct_addresses,
                "consensus_observation_policy": "STRICTLY_PRIOR_SIGNALS_SAME_COIN_DIRECTION",
            }
        )
        reasons["ADMITTED"] += 1
    return admitted, dict(reasons)


def _concentration(rows: Sequence[Mapping[str, Any]], field: str) -> float:
    counts = Counter(str(row.get(field) or "UNKNOWN") for row in rows)
    return max(counts.values(), default=0) / max(1, len(rows))


def explore_copy_vault_vnext_train(report: Mapping[str, Any]) -> dict[str, Any]:
    """Select a consensus freeze candidate without reopening heldout outcomes."""

    physical_freeze_blocked = report.get("provisional_without_physical_freeze") is True
    rows = _train_rows(report)
    grid = [
        (window, minimum)
        for window in CONSENSUS_WINDOWS_MS
        for minimum in MIN_DISTINCT_WALLETS
    ]
    trial_count = len(grid)
    variants: list[dict[str, Any]] = []
    for window, minimum in grid:
        admitted, diagnostics = admit_consensus_train_rows(
            rows,
            window_ms=window,
            minimum_distinct_wallets=minimum,
        )
        stats = summarize_train_rows(
            admitted,
            value_key="net_pnl_usd",
            timestamp_key="signal_ts_ms",
            trial_count=trial_count,
            family_alpha=FAMILY_ALPHA,
        )
        coin_share = _concentration(admitted, "coin")
        vault_share = _concentration(admitted, "vault")
        net = float(stats.get("net_pnl_usd") or 0.0)
        pf = stats.get("profit_factor")
        lcb = stats.get("total_lcb_usd")
        train_statistics_eligible = bool(
            len(admitted) >= MIN_TRAIN_TRADES
            and int(stats.get("distinct_days") or 0) >= MIN_DISTINCT_DAYS
            and net > 0.0
            and pf is not None
            and float(pf) > 1.0
            and lcb is not None
            and float(lcb) > 0.0
            and coin_share <= MAX_COIN_TRADE_SHARE
            and vault_share <= MAX_VAULT_TRADE_SHARE
            and float(stats.get("top_positive_trade_share") or 1.0) <= MAX_TOP_POSITIVE_SHARE
        )
        variants.append(
            {
                "consensus_window_ms": int(window),
                "minimum_distinct_wallets": int(minimum),
                "statistics": stats,
                "largest_coin_trade_share": coin_share,
                "largest_vault_trade_share": vault_share,
                "diagnostics": diagnostics,
                "train_statistics_eligible": train_statistics_eligible,
                "eligible": train_statistics_eligible and not physical_freeze_blocked,
            }
        )
    diagnostic_rows = [row for row in variants if row["train_statistics_eligible"]]
    diagnostic_selected = max(
        diagnostic_rows,
        key=lambda row: (
            float((row["statistics"] or {}).get("total_lcb_usd") or 0.0),
            float((row["statistics"] or {}).get("net_pnl_usd") or 0.0),
            int((row["statistics"] or {}).get("sample_count") or 0),
        ),
        default=None,
    )
    eligible_rows = [row for row in variants if row["eligible"]]
    selected = max(
        eligible_rows,
        key=lambda row: (
            float((row["statistics"] or {}).get("total_lcb_usd") or 0.0),
            float((row["statistics"] or {}).get("net_pnl_usd") or 0.0),
            int((row["statistics"] or {}).get("sample_count") or 0),
        ),
        default=None,
    )
    freeze_candidate = (
        {
            "mechanism": MECHANISM,
            "consensus_window_ms": selected["consensus_window_ms"],
            "minimum_distinct_wallets": selected["minimum_distinct_wallets"],
            "identity_claim": "DISTINCT_RECORDED_WALLET_ADDRESSES_ONLY_NOT_DISTINCT_HUMANS",
            "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        }
        if selected
        else None
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "mechanism": MECHANISM,
        "status": (
            "BASE_COPY_PARAMETERS_NOT_PHYSICALLY_FROZEN"
            if physical_freeze_blocked
            else "TRAIN_ELIGIBLE_TO_FREEZE"
            if selected
            else "NO_ROBUST_TRAIN_CANDIDATE"
        ),
        "selection_eligible": selected is not None,
        "physical_freeze_allowed": selected is not None,
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_evaluated": False,
        "base_parameters_already_frozen": True,
        "physical_freeze_blocked": physical_freeze_blocked,
        "diagnostic_only": physical_freeze_blocked,
        "diagnostic_train_candidate": diagnostic_selected,
        "diagnostic_train_candidate_count": len(diagnostic_rows),
        "diagnostic_not_admitted_pnl": physical_freeze_blocked,
        "identity_claim": "DISTINCT_RECORDED_WALLET_ADDRESSES_ONLY_NOT_DISTINCT_HUMANS",
        "train_rows_seen": len(rows),
        "fixed_grid": {
            "consensus_windows_ms": list(CONSENSUS_WINDOWS_MS),
            "minimum_distinct_wallets": list(MIN_DISTINCT_WALLETS),
            "trial_count": trial_count,
        },
        "selected": selected,
        "freeze_candidate": freeze_candidate,
        "freeze_candidate_sha256": stable_hash(freeze_candidate) if freeze_candidate else None,
        "variants": variants,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "MECHANISM",
    "SCHEMA_VERSION",
    "admit_consensus_train_rows",
    "explore_copy_vault_vnext_train",
]
