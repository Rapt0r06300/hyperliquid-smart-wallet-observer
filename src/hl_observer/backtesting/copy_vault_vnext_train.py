"""Copy-Vault vNext TRAIN-only causal consensus research.

The killed simple whitelist is not reused. A candidate is admitted only when
multiple independently evidenced entities point to the same coin and direction
inside a predeclared causal lookback window. Admission reads no PnL and never
consults validation/OOS/forward. Only already executable, liquidatable and
economically reconciled TRAIN rows are scored afterwards.

Entity normalization reuses the public, point-in-time Copy-Vault consensus gate.
Missing identity evidence reduces effective independence and therefore fails
closed when the quorum cannot be proved. PAPER/READ-ONLY; selection merely
creates a freeze candidate and cannot certify the family.
"""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from hl_observer.backtesting.copy_vault_protocol import (
    MAX_REFERENCE_LAG_MS,
    MAX_TARGET_LAG_MS,
)
from hl_observer.backtesting.train_statistics import (
    exact_lcb_rank_value,
    exact_net_rank_value,
    profit_factor_above_one,
    select_unambiguous_lcb_candidate,
    stable_hash,
    summarize_train_rows,
    top_positive_share_within_limit,
)
from hl_observer.economics.numeric import (
    USD_RECONCILIATION_ABS_TOLERANCE,
    decimal_difference,
    decimal_sum,
    decimal_value,
    float_not_above,
)
from hl_observer.following.entity_consensus import entity_consensus_gate
from hl_observer.instrument_identity import preserve_native_instrument_symbol

SCHEMA_VERSION = "hypersmart.copy_vault_vnext_train.v1"
MECHANISM = "copy_vault_vnext_causal_multiwallet_consensus"
CONSENSUS_WINDOWS_MS = (30_000, 120_000, 300_000)
MIN_DISTINCT_WALLETS = (2, 3)
MIN_TRAIN_TRADES = 8
MIN_DISTINCT_DAYS = 3
MIN_DISTINCT_REGIMES = 2
MAX_COIN_TRADE_SHARE = 0.65
MAX_VAULT_TRADE_SHARE = 0.50
MAX_TOP_POSITIVE_SHARE = 0.60
FAMILY_ALPHA = 0.05
IDENTITY_CLAIM = "ENTITY_NORMALIZED_STRICT_PUBLIC_OR_REPEATED_BEHAVIORAL_EVIDENCE"


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _reconciled_net(row: Mapping[str, Any]) -> Decimal | None:
    if row.get("economic_reconciliation_ok") is False:
        return None

    def amount(field: str) -> Decimal | None:
        exact = row.get(f"{field}_exact_decimal")
        return decimal_value(exact if exact is not None else row.get(field))

    net = amount("net_pnl_usd")
    gross = amount("gross_pnl_usd")
    costs = [
        amount(key)
        for key in (
            "fees_usd",
            "spread_cost_usd",
            "slippage_cost_usd",
            "latency_cost_usd",
        )
    ]
    if net is None or gross is None or any(cost is None or cost < 0 for cost in costs):
        return None
    expected = decimal_sum(
        (gross, *(cost.copy_negate() for cost in costs if cost is not None))
    )
    reconciliation_delta = decimal_difference(expected, net)
    if (
        expected is None
        or reconciliation_delta is None
        or reconciliation_delta.copy_abs() > USD_RECONCILIATION_ABS_TOLERANCE
    ):
        return None
    # The tolerated discrepancy is uncertainty, never extra credited PnL.
    return min(net, expected)


def _reconciled(row: Mapping[str, Any]) -> bool:
    return _reconciled_net(row) is not None


def _execution_evidence_complete(row: Mapping[str, Any]) -> bool:
    positive_fields = (
        "entry_price",
        "exit_price",
        "notional_usd",
        "entry_capacity_usd",
        "exit_capacity_usd",
    )
    nonnegative_fields = (
        "reference_lag_ms",
        "entry_target_lag_ms",
        "exit_target_lag_ms",
        "observed_latency_ms",
        "fees_usd",
        "spread_cost_usd",
        "slippage_cost_usd",
        "latency_cost_usd",
    )
    positive = {field: _number(row.get(field)) for field in positive_fields}
    nonnegative = {field: _number(row.get(field)) for field in nonnegative_fields}
    if any(value is None or value <= 0.0 for value in positive.values()):
        return False
    if any(value is None or value < 0.0 for value in nonnegative.values()):
        return False
    if (
        float(nonnegative["reference_lag_ms"]) > MAX_REFERENCE_LAG_MS
        or float(nonnegative["entry_target_lag_ms"]) > MAX_TARGET_LAG_MS
        or float(nonnegative["exit_target_lag_ms"]) > MAX_TARGET_LAG_MS
    ):
        return False
    notional = float(positive["notional_usd"])
    return (
        float(positive["entry_capacity_usd"]) >= notional
        and float(positive["exit_capacity_usd"]) >= notional
    )


def _train_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    trades = report.get("trades")
    if not isinstance(trades, list):
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_metaorders: set[str] = set()
    for raw in trades:
        if not isinstance(raw, Mapping):
            continue
        segment = str(raw.get("walk_forward_segment") or raw.get("segment") or "").lower()
        if segment != "train":
            continue
        trade_id = str(raw.get("trade_id") or "")
        vault = str(raw.get("vault") or "").strip().lower()
        coin = preserve_native_instrument_symbol(raw.get("coin"))
        try:
            direction = int(raw.get("direction") or 0)
            signal_ts_ms = int(raw.get("signal_ts_ms") or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        conservative_net = _reconciled_net(raw)
        if (
            not trade_id
            or trade_id in seen
            or not vault
            or not coin
            or direction not in (-1, 1)
            or signal_ts_ms <= 0
            or raw.get("liquidatable_net") is not True
            or not _execution_evidence_complete(raw)
            or conservative_net is None
        ):
            continue
        metaorder_id = str(raw.get("metaorder_id") or "").strip()
        if metaorder_id:
            if metaorder_id in seen_metaorders:
                continue
            seen_metaorders.add(metaorder_id)
        accepted_net = float_not_above(conservative_net)
        if accepted_net is None:
            continue
        seen.add(trade_id)
        accepted = dict(raw)
        accepted["net_pnl_usd_exact_decimal"] = format(conservative_net, "f")
        accepted["net_pnl_usd"] = accepted_net
        result.append(accepted)
    result.sort(key=lambda row: (int(row["signal_ts_ms"]), str(row["trade_id"])))
    return result


def _identity_vote(row: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt a causal Copy-Vault row to the canonical entity-consensus schema."""

    direction = int(row.get("direction") or 0)
    return {
        "wallet": str(row.get("vault") or "").strip().lower(),
        "coin": preserve_native_instrument_symbol(row.get("coin")),
        "side": "long" if direction == 1 else "short",
        "ts_ms": int(row.get("signal_ts_ms") or 0),
        "size": _number(row.get("notional_usd")),
        "public_entity_id": row.get("public_entity_id"),
        "twap_cadence_ms": row.get("twap_cadence_ms"),
        "funding_profile": row.get("funding_profile"),
        "hedge_profile": row.get("hedge_profile"),
    }


def _causal_entity_keys(
    row: Mapping[str, Any], identity: Mapping[str, Any]
) -> tuple[str | None, str | None]:
    """Return the current wallet's causal economic entity key and inferred cluster."""

    current_vault = str(row.get("vault") or "").strip().lower()
    if not current_vault:
        return None, None
    cluster_id: str | None = None
    for cluster in identity.get("clusters") or []:
        if not isinstance(cluster, Mapping):
            continue
        wallets = {
            str(wallet).strip().lower()
            for wallet in (cluster.get("wallets") or [])
            if str(wallet).strip()
        }
        if current_vault in wallets:
            candidate = str(cluster.get("cluster_id") or "").strip()
            if candidate:
                cluster_id = candidate
            break
    if not cluster_id:
        return None, None
    public_entity_id = str(row.get("public_entity_id") or "").strip()
    concentration_key = (
        f"public:{public_entity_id}" if public_entity_id else f"cluster:{cluster_id}"
    )
    return concentration_key, cluster_id


def admit_consensus_train_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    window_ms: int,
    minimum_distinct_wallets: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Apply prior-only entity-normalized consensus; PnL is never read here."""

    ordered = sorted(
        [dict(row) for row in rows],
        key=lambda row: (int(row.get("signal_ts_ms") or 0), str(row.get("trade_id") or "")),
    )
    admitted: list[dict[str, Any]] = []
    reasons = Counter()
    for index, row in enumerate(ordered):
        timestamp = int(row.get("signal_ts_ms") or 0)
        coin = preserve_native_instrument_symbol(row.get("coin"))
        direction = int(row.get("direction") or 0)
        current_vault = str(row.get("vault") or "").lower()
        supporting_rows: list[dict[str, Any]] = []
        prior_vaults: set[str] = set()
        for previous in reversed(ordered[:index]):
            previous_ts = int(previous.get("signal_ts_ms") or 0)
            age = timestamp - previous_ts
            if age > int(window_ms):
                break
            if age <= 0:
                continue
            if (
                preserve_native_instrument_symbol(previous.get("coin")) == coin
                and int(previous.get("direction") or 0) == direction
            ):
                vault = str(previous.get("vault") or "").lower()
                if vault and vault != current_vault:
                    prior_vaults.add(vault)
                    supporting_rows.append(previous)
        distinct_addresses = len(prior_vaults | {current_vault}) if current_vault else len(prior_vaults)
        if distinct_addresses < int(minimum_distinct_wallets):
            reasons["INSUFFICIENT_PRIOR_DISTINCT_WALLET_CONSENSUS"] += 1
            continue
        identity = entity_consensus_gate(
            [_identity_vote(item) for item in [*reversed(supporting_rows), row]],
            min_independent_votes=float(minimum_distinct_wallets),
            strict=True,
            as_of_ms=timestamp,
        )
        if identity.get("decision") != "ALLOW_SHADOW":
            reasons["ENTITY_INDEPENDENCE_NOT_PROVEN"] += 1
            continue
        concentration_key, cluster_id = _causal_entity_keys(row, identity)
        if not concentration_key or not cluster_id:
            reasons["ENTITY_CLUSTER_ASSIGNMENT_NOT_PROVEN"] += 1
            continue
        admitted.append(
            {
                **row,
                "consensus_window_ms": int(window_ms),
                "minimum_distinct_wallets": int(minimum_distinct_wallets),
                "prior_supporting_wallet_addresses": sorted(prior_vaults),
                "distinct_wallet_addresses_at_signal": distinct_addresses,
                "entity_cluster_count_at_signal": int(identity["entity_cluster_count"]),
                "effective_independent_votes_at_signal": float(identity["effective_independent_votes"]),
                "entity_independence_measurable": bool(identity["independence_measurable"]),
                "entity_consensus_warnings": list(identity.get("warnings") or []),
                "entity_concentration_key_at_signal": concentration_key,
                "entity_cluster_id_at_signal": cluster_id,
                "consensus_observation_policy": "STRICTLY_PRIOR_ENTITY_NORMALIZED_SAME_COIN_DIRECTION",
            }
        )
        reasons["ADMITTED"] += 1
    return admitted, dict(reasons)


def _concentration(rows: Sequence[Mapping[str, Any]], field: str) -> float:
    counts = Counter(str(row.get(field) or "UNKNOWN") for row in rows)
    return max(counts.values(), default=0) / max(1, len(rows))


def _distinct_regimes(rows: Sequence[Mapping[str, Any]]) -> int:
    """Count explicit TRAIN regime labels; missing evidence contributes no regime."""

    return len(
        {
            regime
            for row in rows
            if (regime := str(row.get("regime_id") or "").strip())
        }
    )


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
        entity_share = _concentration(admitted, "entity_concentration_key_at_signal")
        distinct_regimes = _distinct_regimes(admitted)
        net = decimal_value(stats.get("net_pnl_usd_exact_decimal"))
        lcb = decimal_value(stats.get("total_lcb_usd_exact_decimal"))
        train_statistics_eligible = bool(
            len(admitted) >= MIN_TRAIN_TRADES
            and int(stats.get("distinct_days") or 0) >= MIN_DISTINCT_DAYS
            and distinct_regimes >= MIN_DISTINCT_REGIMES
            and net is not None
            and net > 0
            and profit_factor_above_one(stats)
            and stats.get("lcb_status") == "MEASURED"
            and lcb is not None
            and lcb > 0
            and coin_share <= MAX_COIN_TRADE_SHARE
            and entity_share <= MAX_VAULT_TRADE_SHARE
            and top_positive_share_within_limit(stats, MAX_TOP_POSITIVE_SHARE)
        )
        variants.append(
            {
                "consensus_window_ms": int(window),
                "minimum_distinct_wallets": int(minimum),
                "statistics": stats,
                "distinct_regimes": distinct_regimes,
                "minimum_distinct_regimes": MIN_DISTINCT_REGIMES,
                "largest_coin_trade_share": coin_share,
                "largest_vault_trade_share": entity_share,
                "largest_entity_trade_share": entity_share,
                "concentration_unit": "CAUSAL_ECONOMIC_ENTITY",
                "diagnostics": diagnostics,
                "train_statistics_eligible": train_statistics_eligible,
                "eligible": train_statistics_eligible and not physical_freeze_blocked,
            }
        )
    diagnostic_rows = [row for row in variants if row["train_statistics_eligible"]]
    # Diagnostics may name the nominal top row but never authorize a freeze.
    # The separate resolution status makes an overlapping rank explicit.
    diagnostic_selected = max(
        diagnostic_rows,
        key=lambda row: (
            exact_lcb_rank_value(row["statistics"] or {}),
            exact_net_rank_value(row["statistics"] or {}),
            int((row["statistics"] or {}).get("sample_count") or 0),
        ),
        default=None,
    )
    _, diagnostic_selection_resolution = select_unambiguous_lcb_candidate(
        diagnostic_rows
    )
    eligible_rows = [row for row in variants if row["eligible"]]
    selected, selection_resolution = select_unambiguous_lcb_candidate(eligible_rows)
    freeze_candidate = (
        {
            "mechanism": MECHANISM,
            "consensus_window_ms": selected["consensus_window_ms"],
            "minimum_distinct_wallets": selected["minimum_distinct_wallets"],
            "minimum_distinct_regimes": MIN_DISTINCT_REGIMES,
            "identity_claim": IDENTITY_CLAIM,
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
        "selection_numeric_resolution": selection_resolution,
        "diagnostic_selection_numeric_resolution": diagnostic_selection_resolution,
        "physical_freeze_allowed": selected is not None,
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_evaluated": False,
        "base_parameters_already_frozen": True,
        "physical_freeze_blocked": physical_freeze_blocked,
        "diagnostic_only": physical_freeze_blocked,
        "diagnostic_train_candidate": diagnostic_selected,
        "diagnostic_train_candidate_count": len(diagnostic_rows),
        "diagnostic_not_admitted_pnl": physical_freeze_blocked,
        "identity_claim": IDENTITY_CLAIM,
        "train_rows_seen": len(rows),
        "fixed_grid": {
            "consensus_windows_ms": list(CONSENSUS_WINDOWS_MS),
            "minimum_distinct_wallets": list(MIN_DISTINCT_WALLETS),
            "minimum_distinct_regimes": MIN_DISTINCT_REGIMES,
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
