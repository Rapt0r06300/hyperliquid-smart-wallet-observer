"""Strict, shared proof contract for per-family paper economic objectives.

Displayed/modelled PnL is kept separate from PnL eligible for an economic claim.
Missing costs, identities, forward proof, paper guards or Cross-Venue atomic
provenance fail closed.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Iterable

from hl_observer.backtesting.copy_vault_protocol import CHECKPOINT_INTEGRITY_SCHEMA
from hl_observer.backtesting.cross_venue_certified import (
    FOUR_FILL_CONTRACT_VERSION,
    SOURCE_MODE as CROSS_CERTIFIED_SOURCE_MODE,
)

TARGET_NET_USD = 4.0
TARGET_NET_USD_PER_DAY = 4.0
MIN_PROOF_DAYS = 2
STARTING_CAPITAL_USD = 1000.0
COPY_HELDOUT_MIN_N = 20
CANONICAL_FAMILIES = ("copy_vault", "lead_lag", "cross_venue_dislocation_v2")
_ALIASES = {
    "copy-vault": "copy_vault", "copy_vault": "copy_vault",
    "lead-lag": "lead_lag", "lead_lag": "lead_lag",
    "arbitrage": "cross_venue_dislocation_v2",
    "cross_venue_dislocation": "cross_venue_dislocation_v2",
    "cross_venue_dislocation_v2": "cross_venue_dislocation_v2",
}
_ECONOMIC_KEYS = ("gross_pnl_usd", "fees_usd", "spread_cost_usd", "slippage_cost_usd", "latency_cost_usd", "net_pnl_usd")
_COST_KEYS = ("fees_usd", "spread_cost_usd", "slippage_cost_usd", "latency_cost_usd")


def canonical_family(value: object) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    return _ALIASES.get(normalized, normalized)


def evaluate_daily_net(
    trades: Iterable[Mapping[str, Any]],
    *,
    target_net_usd_per_day: float = TARGET_NET_USD_PER_DAY,
) -> dict[str, Any]:
    """Aggregate supplied closed-trade net PnL by UTC exit day, fail closed."""

    target = _number(target_net_usd_per_day)
    if target is None:
        raise ValueError("target_net_usd_per_day must be finite")
    daily: dict[str, float] = {}
    counts: dict[str, int] = {}
    missing_trade_timestamps = 0
    missing_trade_net = 0
    observed_trades = 0
    for trade in trades:
        observed_trades += 1
        if not isinstance(trade, Mapping):
            missing_trade_timestamps += 1
            missing_trade_net += 1
            continue
        timestamp = next(
            (
                value
                for key in ("exit_ts_ms", "ts_out", "close_ts_ms", "timestamp_ms")
                for value in [_number(trade.get(key))]
                if value is not None
            ),
            None,
        )
        if timestamp is None:
            timestamp_ns = next(
                (
                    value
                    for key in (
                        "exit_ts_ns",
                        "ts_out_ns",
                        "close_ts_ns",
                        "timestamp_ns",
                    )
                    for value in [_number(trade.get(key))]
                    if value is not None
                ),
                None,
            )
            if timestamp_ns is not None:
                timestamp = timestamp_ns / 1_000_000.0
        net = next(
            (
                value
                for key in ("net_pnl_usd", "net_usd", "net")
                for value in [_number(trade.get(key))]
                if value is not None
            ),
            None,
        )
        if timestamp is None:
            missing_trade_timestamps += 1
        if net is None:
            missing_trade_net += 1
        if timestamp is None or net is None:
            continue
        try:
            day = datetime.fromtimestamp(
                timestamp / 1000.0, tz=timezone.utc
            ).date().isoformat()
        except (OSError, OverflowError, ValueError):
            missing_trade_timestamps += 1
            continue
        daily[day] = daily.get(day, 0.0) + net
        counts[day] = counts.get(day, 0) + 1

    days = [
        {
            "date_utc": day,
            "net_pnl_usd": round(value, 8),
            "trade_count": counts[day],
            "at_or_above_target": value >= target,
        }
        for day, value in sorted(daily.items())
    ]
    values = [float(row["net_pnl_usd"]) for row in days]
    return {
        "schema_version": "hypersmart.daily_net_evidence.v1",
        "target_net_usd_per_day": float(target),
        "minimum_required_days": MIN_PROOF_DAYS,
        "sample_count": len(values),
        "observed_trade_count": observed_trades,
        "missing_trade_timestamps": missing_trade_timestamps,
        "missing_trade_net": missing_trade_net,
        "days": days,
        "total_net_pnl_usd": round(sum(values), 8) if values else None,
        "mean_daily_net_pnl_usd": (
            round(sum(values) / len(values), 8) if values else None
        ),
        "min_daily_net_pnl_usd": round(min(values), 8) if values else None,
        "all_days_at_or_above_target": bool(
            values
            and len(values) >= MIN_PROOF_DAYS
            and missing_trade_timestamps == 0
            and missing_trade_net == 0
            and min(values) >= target
        ),
    }


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _segment_economics(segment: Mapping[str, Any] | None, *, label: str, issues: list[str]) -> dict[str, Any] | None:
    if not isinstance(segment, Mapping):
        return None
    metrics = {key: _number(segment.get(key)) for key in _ECONOMIC_KEYS}
    missing = [key for key, value in metrics.items() if value is None]
    issues.extend(f"{label}_UNMEASURED:{key}" for key in missing)
    for key in _COST_KEYS:
        if metrics[key] is not None and metrics[key] < 0:
            issues.append(f"{label}_NEGATIVE_COST:{key}")
    reconciled = False
    if not missing:
        expected = metrics["gross_pnl_usd"] - sum(metrics[key] for key in _COST_KEYS)
        reconciled = math.isclose(expected, metrics["net_pnl_usd"], abs_tol=1e-4)
        if not reconciled:
            issues.append(f"{label}_ECONOMIC_RECONCILIATION_FAILED")
    count = _number(segment.get("sample_count")); trade_count = _number(segment.get("trade_ids_count")); duplicates = _number(segment.get("duplicate_trade_ids")); trade_hash = str(segment.get("trade_ids_sha256") or "")
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
    period = evidence.get("period"); period = period if isinstance(period, Mapping) else {}
    meta = period.get("collection_meta"); meta = meta if isinstance(meta, Mapping) else {}
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
    if family not in CANONICAL_FAMILIES:
        issues.append("NON_CANONICAL_OR_INACTIVE_FAMILY")
    if evidence.get("paper_read_only") is not True or evidence.get("real_execution") is not False:
        issues.append("NOT_PAPER_READ_ONLY")
    capital = _number(evidence.get("starting_capital_usd"))
    if capital != STARTING_CAPITAL_USD:
        issues.append("INVALID_STARTING_CAPITAL")
    if evidence.get("parameters_frozen") is not True:
        issues.append("PARAMETERS_NOT_FROZEN_BEFORE_EVALUATION")
    opened = _number(evidence.get("opened_positions")); closed = _number(evidence.get("closed_positions"))
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
            heldout_n = _number(generalisation.get("sample_count")); heldout_net_bps = _number(generalisation.get("net_bps"))
            if heldout_n is None or heldout_n < COPY_HELDOUT_MIN_N:
                issues.append("COPY_HELDOUT_VAULT_SAMPLE_TOO_SMALL")
            if heldout_net_bps is None:
                issues.append("COPY_HELDOUT_VAULT_NET_MISSING")
            elif heldout_net_bps <= 0:
                issues.append("COPY_HELDOUT_VAULT_NET_NOT_POSITIVE")
    metrics = {key: _number(evidence.get(key)) for key in _ECONOMIC_KEYS}
    missing = [key for key, value in metrics.items() if value is None]
    issues.extend(f"UNMEASURED:{key}" for key in missing)
    for key in _COST_KEYS:
        if metrics[key] is not None and metrics[key] < 0:
            issues.append(f"NEGATIVE_COST:{key}")
    if not missing:
        expected = metrics["gross_pnl_usd"] - sum(metrics[key] for key in _COST_KEYS)
        if not math.isclose(expected, metrics["net_pnl_usd"], abs_tol=1e-4):
            issues.append("ECONOMIC_RECONCILIATION_FAILED")
    liquidatable = evidence.get("liquidatable_net")
    if liquidatable is None:
        liquidatable = evidence.get("LIQUIDATABLE_NET")
    if liquidatable is not True:
        issues.append("NOT_LIQUIDATABLE_NET")
    duplicates = _number(evidence.get("duplicate_trade_ids")); trade_count = _number(evidence.get("trade_ids_count")); trade_hash = str(evidence.get("trade_ids_sha256") or "")
    if duplicates != 0:
        issues.append("DUPLICATE_TRADE_IDENTITIES")
    if closed is None or trade_count != closed or len(trade_hash) != 64:
        issues.append("TRADE_ID_PROOF_INCOMPLETE")
    oos = evidence.get("oos"); forward = evidence.get("forward"); placebos = evidence.get("placebos")
    oos_net = _number(oos.get("net_pnl_usd")) if isinstance(oos, Mapping) else None; oos_count = _number(oos.get("sample_count")) if isinstance(oos, Mapping) else None
    forward_net = _number(forward.get("net_pnl_usd")) if isinstance(forward, Mapping) else None; forward_count = _number(forward.get("sample_count")) if isinstance(forward, Mapping) else None
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
            if daily_sample_count < MIN_PROOF_DAYS:
                issues.append("DAILY_NET_PROOF_TOO_SHORT")
            if not (
                daily_evidence.get("schema_version")
                == "hypersmart.daily_net_evidence.v1"
                and _number(daily_evidence.get("target_net_usd_per_day"))
                == TARGET_NET_USD_PER_DAY
                and daily_sample_count > 0
                and _number(daily_evidence.get("missing_trade_timestamps")) == 0
                and _number(daily_evidence.get("missing_trade_net")) == 0
                and (_number(daily_evidence.get("min_daily_net_pnl_usd")) or -math.inf)
                >= TARGET_NET_USD_PER_DAY
                and daily_evidence.get("all_days_at_or_above_target") is True
            ):
                issues.append("DAILY_NET_TARGET_NOT_REACHED")
    proof_economics = None
    if oos_economics is not None and forward_economics is not None:
        proof_economics = {key: round(float(oos_economics[key]) + float(forward_economics[key]), 8) for key in _ECONOMIC_KEYS}
        proof_economics["sample_count"] = int(oos_economics["sample_count"]) + int(forward_economics["sample_count"])
        proof_economics["trade_ids_count"] = proof_economics["sample_count"]
        proof_economics["trade_ids_sha256"] = hashlib.sha256((str(oos_economics["trade_ids_sha256"]) + "\n" + str(forward_economics["trade_ids_sha256"])).encode("utf-8")).hexdigest()
    proof_net = float(proof_economics["net_pnl_usd"]) if proof_economics is not None else None
    if proof_net is None or proof_net < float(target_net_usd):
        issues.append("TARGET_NET_USD_NOT_REACHED")
    unique_issues = list(dict.fromkeys(issues))
    return {"family": family, "target_net_usd": float(target_net_usd), "target_net_usd_per_day": TARGET_NET_USD_PER_DAY, "daily_target_required": daily_target_required, "daily_evidence": dict(daily_evidence) if isinstance(daily_evidence, Mapping) else None, "copy_checkpoint_integrity": dict(evidence["copy_checkpoint_integrity"]) if isinstance(evidence.get("copy_checkpoint_integrity"), Mapping) else None, "proof_economics": proof_economics, "proof_net_pnl_usd": proof_net, "eligible_net_pnl_usd": proof_net if not unique_issues else None, "objective_status": "ATTEINT" if not unique_issues else "NON_ATTEINT", "objective_reasons": unique_issues}


__all__ = ["CANONICAL_FAMILIES", "COPY_HELDOUT_MIN_N", "MIN_PROOF_DAYS", "STARTING_CAPITAL_USD", "TARGET_NET_USD", "TARGET_NET_USD_PER_DAY", "canonical_family", "evaluate_daily_net", "evaluate_objective"]
