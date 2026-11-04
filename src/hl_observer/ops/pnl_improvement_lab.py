"""Historical PnL lab for local HyperSmart paper sessions.

The live dashboard intentionally ignores stale logs. Historical research must
do the opposite: read every canonical archived session, while preserving
session boundaries and chronology. This module reconstructs OPEN -> CLOSE
round trips, reconciles stored gross PnL from prices, and evaluates only entry
rules that were knowable before a trade closed.

Nothing in this module changes runtime flags. Results are research hypotheses
until they survive chronological train/validation/holdout checks and a later
exact replay on market marks.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from hl_observer.simulation.accounting_truth import (
    ACCOUNTING_SCHEMA_VERSION,
    finite_number,
    first_not_none,
    round_trip_net_pnl_usdc,
)
from hl_observer.backtesting.regime_label import freeze_regime_allowlist_from_train
from hl_observer.research.market_quality import compare_copy_vault_liquidity_veto

CANONICAL_LEDGER_NAME = "simulation_pnl_ledger_latest.jsonl"
DEFAULT_COMPARISON_NOTIONAL_USDT = 50.0
LEGACY_UNEVIDENCED_MARKER = "LEGACY_UNEVIDENCED"
MIN_TOTAL_TRADES = 30
MIN_COIN_BLACKLIST_TRADES = 30
MIN_COIN_BLACKLIST_TIME_SLICES = 3


def _strict_positive_timestamp(value: object) -> int | None:
    """Return only an integer millisecond timestamp; never coerce future data."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _markout_leader_key(
    row: Mapping[str, Any],
    leader_fields: Sequence[str],
) -> str | None:
    for field in leader_fields:
        value = row.get(field)
        if value is not None and str(value).strip():
            return str(value).strip().lower()
    return None


def _causal_markout_observation(
    row: object,
    *,
    leader_fields: Sequence[str],
    entry_ts_field: str,
    observed_ts_field: str,
    markout_field: str,
) -> tuple[str, int, int, float] | None:
    """Parse one realized markout while preserving the causal timestamp contract."""

    if not isinstance(row, Mapping):
        return None
    leader = _markout_leader_key(row, leader_fields)
    entry_ts = _strict_positive_timestamp(row.get(entry_ts_field))
    observed_ts = _strict_positive_timestamp(row.get(observed_ts_field))
    markout = finite_number(row.get(markout_field))
    if (
        leader is None
        or entry_ts is None
        or observed_ts is None
        or observed_ts <= entry_ts
        or markout is None
    ):
        return None
    return leader, entry_ts, observed_ts, float(markout)


def learn_train_only_markout_filter(
    train_rows: Sequence[Mapping[str, Any]],
    candidate_rows: Sequence[Mapping[str, Any]],
    *,
    min_history: int = 5,
    thresholds_bps: Sequence[float] = (0.0, 1.0, 5.0, 9.0),
    leader_fields: Sequence[str] = (
        "leader_id",
        "leader_wallet",
        "wallet_address",
        "wallet",
    ),
    entry_ts_field: str = "entry_ts_ms",
    observed_ts_field: str = "markout_observed_at_ms",
    markout_field: str = "markout_bps",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Learn a markout gate from TRAIN and apply its frozen value to candidates.

    A row's realized markout is usable as a *historical observation* only after its
    own entry.  For every TRAIN example, the score is computed from observations
    whose observation timestamp is strictly before that example's entry timestamp.
    The chosen threshold is then frozen.  Candidate rows are scored only against
    TRAIN observations with ``observed_ts < candidate.entry_ts``; candidate
    markout fields are deliberately never read.  Missing or out-of-order evidence
    rejects the row instead of creating a zero or a guessed score.
    """

    minimum_history = int(min_history)
    if minimum_history < 1:
        raise ValueError("min_history must be >= 1")
    thresholds = tuple(sorted({float(value) for value in thresholds_bps}))
    if not thresholds or any(not math.isfinite(value) for value in thresholds):
        raise ValueError("thresholds_bps must contain finite values")

    observations: list[tuple[str, int, int, float]] = []
    invalid_train = 0
    for raw in train_rows or ():
        observation = _causal_markout_observation(
            raw,
            leader_fields=leader_fields,
            entry_ts_field=entry_ts_field,
            observed_ts_field=observed_ts_field,
            markout_field=markout_field,
        )
        if observation is None:
            invalid_train += 1
            continue
        observations.append(observation)
    observations.sort(key=lambda item: (item[1], item[2], item[0]))

    history: defaultdict[str, list[tuple[int, float]]] = defaultdict(list)
    training_examples: list[tuple[float, float]] = []
    for leader, entry_ts, observed_ts, markout in observations:
        prior = [value for prior_ts, value in history[leader] if prior_ts < entry_ts]
        if len(prior) >= minimum_history:
            training_examples.append((sum(prior) / len(prior), markout))
        history[leader].append((observed_ts, markout))

    eligible_thresholds: list[tuple[float, float, int]] = []
    for threshold in thresholds:
        selected = [outcome for score, outcome in training_examples if score >= threshold]
        if len(selected) < minimum_history:
            continue
        eligible_thresholds.append((sum(selected) / len(selected), threshold, len(selected)))
    if not eligible_thresholds:
        return [], {
            "status": "INSUFFICIENT_TRAIN_MARKOUT_HISTORY",
            "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
            "train_rows": len(train_rows),
            "valid_train_observations": len(observations),
            "invalid_train_rows_rejected": invalid_train,
            "training_examples": len(training_examples),
            "minimum_history": minimum_history,
            "threshold_candidates_bps": list(thresholds),
            "learned_threshold_bps": None,
            "candidate_rows": len(candidate_rows),
            "candidate_selected": 0,
            "candidate_future_markout_ignored": True,
            "paper_read_only": True,
            "real_execution": False,
        }

    # Deterministic tie-break: maximize TRAIN mean, then coverage, then prefer
    # the stricter threshold.  No candidate/OOS outcome participates here.
    _, learned_threshold, _ = max(
        eligible_thresholds,
        key=lambda item: (item[0], item[2], item[1]),
    )
    selected_candidates: list[dict[str, Any]] = []
    rejected_invalid = 0
    rejected_history = 0
    for raw in candidate_rows or ():
        if not isinstance(raw, Mapping):
            rejected_invalid += 1
            continue
        leader = _markout_leader_key(raw, leader_fields)
        entry_ts = _strict_positive_timestamp(raw.get(entry_ts_field))
        if leader is None or entry_ts is None:
            rejected_invalid += 1
            continue
        prior = [
            value
            for observed_ts, value in history.get(leader, ())
            if observed_ts < entry_ts
        ]
        if len(prior) < minimum_history:
            rejected_history += 1
            continue
        score = sum(prior) / len(prior)
        if score < learned_threshold:
            continue
        selected_candidates.append(
            {
                **dict(raw),
                "markout_filter_score_bps": round(score, 8),
                "markout_filter_threshold_bps": round(learned_threshold, 8),
                "markout_filter_history_count": len(prior),
                "markout_filter_training_only": True,
                "markout_filter_uses_candidate_future": False,
            }
        )

    return selected_candidates, {
        "status": "TRAIN_FILTER_FROZEN",
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "train_rows": len(train_rows),
        "valid_train_observations": len(observations),
        "invalid_train_rows_rejected": invalid_train,
        "training_examples": len(training_examples),
        "minimum_history": minimum_history,
        "threshold_candidates_bps": list(thresholds),
        "learned_threshold_bps": round(learned_threshold, 8),
        "candidate_rows": len(candidate_rows),
        "candidate_selected": len(selected_candidates),
        "candidate_rejected_invalid": rejected_invalid,
        "candidate_rejected_insufficient_history": rejected_history,
        "candidate_future_markout_ignored": True,
        "feature_fields": [entry_ts_field, observed_ts_field, markout_field],
        "paper_read_only": True,
        "real_execution": False,
    }


def compare_regime_ablation(
    train_rows: Sequence[Mapping[str, Any]],
    oos_rows: Sequence[Mapping[str, Any]],
    *,
    cutoff_ms: int,
    regime_field: str = "regime",
    gross_pnl_field: str = "gross_pnl_bps",
    cost_field: str = "cost_bps",
    opened_at_field: str = "opened_at_ms",
    episode_id_field: str = "episode_id",
    trial_id_field: str = "trial_id",
    min_trades_per_regime: int = 3,
    min_mean_net_bps: float = 0.0,
) -> dict[str, Any]:
    """Compare all OOS episodes with a frozen TRAIN regime allow-list.

    The same OOS rows and explicit cost field are used for the baseline and
    filtered arm.  Missing fields, future TRAIN rows, pre-cutoff OOS rows and
    duplicate episode identifiers make the result ``UNMEASURABLE``.  This is a
    diagnostic ablation only; it never changes runtime activation.
    """

    if isinstance(cutoff_ms, bool) or not isinstance(cutoff_ms, int) or cutoff_ms <= 0:
        return {"status": "UNMEASURABLE", "reason": "INVALID_CUTOFF", "paper_read_only": True}

    def _parse(rows: Sequence[Mapping[str, Any]], *, is_train: bool) -> tuple[list[dict[str, Any]], str | None]:
        parsed: list[dict[str, Any]] = []
        seen_episodes: set[str] = set()
        for row in rows or ():
            if not isinstance(row, Mapping):
                return [], "INVALID_ROW"
            regime = str(row.get(regime_field) or "").strip()
            episode = str(row.get(episode_id_field) or "").strip()
            trial = str(row.get(trial_id_field) or "").strip()
            ts = row.get(opened_at_field)
            try:
                gross = float(row.get(gross_pnl_field))
                cost = float(row.get(cost_field))
            except (TypeError, ValueError):
                return [], "INVALID_NUMERIC_EVIDENCE"
            if (
                not regime
                or not episode
                or not trial
                or episode in seen_episodes
                or isinstance(ts, bool)
                or not isinstance(ts, int)
                or ts <= 0
                or not math.isfinite(gross)
                or not math.isfinite(cost)
                or cost < 0
                or (is_train and ts > cutoff_ms)
                or (not is_train and ts <= cutoff_ms)
            ):
                return [], "INVALID_SPLIT_OR_DUPLICATE_EPISODE"
            seen_episodes.add(episode)
            parsed.append(
                {
                    "regime": regime,
                    "episode_id": episode,
                    "trial_id": trial,
                    "gross_pnl_bps": gross,
                    "cost_bps": cost,
                    "net_pnl_bps": gross - cost,
                }
            )
        return parsed, None

    train, train_error = _parse(train_rows, is_train=True)
    oos, oos_error = _parse(oos_rows, is_train=False)
    if train_error or oos_error or not train or not oos:
        return {
            "status": "UNMEASURABLE",
            "reason": train_error or oos_error or "EMPTY_SPLIT",
            "train_rows": len(train_rows or ()),
            "oos_rows": len(oos_rows or ()),
            "paper_read_only": True,
            "real_execution": False,
        }

    freeze = freeze_regime_allowlist_from_train(
        train,
        regime_field="regime",
        gross_pnl_field="gross_pnl_bps",
        cost_field="cost_bps",
        min_trades_per_regime=min_trades_per_regime,
        min_mean_net_bps=min_mean_net_bps,
    )

    def _metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {
                "rows": 0,
                "trials": 0,
                "gross_pnl_bps": None,
                "cost_bps": None,
                "net_pnl_bps": None,
                "mean_net_pnl_bps": None,
            }
        net = sum(float(row["net_pnl_bps"]) for row in rows)
        gross = sum(float(row["gross_pnl_bps"]) for row in rows)
        cost = sum(float(row["cost_bps"]) for row in rows)
        return {
            "rows": len(rows),
            "trials": len({str(row["trial_id"]) for row in rows}),
            "gross_pnl_bps": round(gross, 8),
            "cost_bps": round(cost, 8),
            "net_pnl_bps": round(net, 8),
            "mean_net_pnl_bps": round(net / len(rows), 8),
        }

    allowed = set(freeze["allowed_regimes"])
    selected = [row for row in oos if row["regime"] in allowed]
    baseline_metrics = _metrics(oos)
    selected_metrics = _metrics(selected)
    comparable = bool(allowed and selected)
    delta = (
        round(selected_metrics["mean_net_pnl_bps"] - baseline_metrics["mean_net_pnl_bps"], 8)
        if comparable
        else None
    )
    return {
        "status": "COMPARABLE" if comparable else "UNMEASURABLE",
        "reason": None if comparable else "NO_ELIGIBLE_OOS_REGIME",
        "cutoff_ms": cutoff_ms,
        "train_freeze": freeze,
        "baseline_oos": baseline_metrics,
        "regime_filtered_oos": selected_metrics,
        "delta_mean_net_pnl_bps": delta,
        "cost_model": "net_pnl_bps=gross_pnl_bps-cost_bps",
        "same_oos_episodes_and_cost_fields": True,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
    }


def prioritize_falsifiable_experiments(
    experiments: Iterable[Mapping[str, Any]], *, limit: int = 5
) -> dict[str, Any]:
    """Select high-information falsifiable tests without repeating a sweep."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_sweeps: set[str] = set()
    for raw in experiments:
        if not isinstance(raw, Mapping):
            return {"status": "UNMEASURABLE", "reason": "INVALID_EXPERIMENT", "paper_read_only": True, "real_execution": False}
        experiment_id = raw.get("experiment_id")
        hypothesis = raw.get("hypothesis")
        protocol = raw.get("validation_protocol")
        sweep = str(raw.get("sweep_signature") or experiment_id or "").strip()
        try:
            information_gain = float(raw.get("information_gain"))
            falsification_cost = float(raw.get("falsification_cost"))
        except (TypeError, ValueError, OverflowError):
            return {"status": "UNMEASURABLE", "reason": "INVALID_INFORMATION_OR_COST", "paper_read_only": True, "real_execution": False}
        if (
            not isinstance(experiment_id, str) or not experiment_id.strip()
            or experiment_id in seen_ids or not isinstance(hypothesis, str) or not hypothesis.strip()
            or not isinstance(protocol, str) or not protocol.strip()
            or not sweep or sweep in seen_sweeps
            or not math.isfinite(information_gain) or information_gain < 0
            or not math.isfinite(falsification_cost) or falsification_cost < 0
        ):
            return {"status": "UNMEASURABLE", "reason": "INVALID_OR_REPEATED_EXPERIMENT", "paper_read_only": True, "real_execution": False}
        seen_ids.add(experiment_id)
        seen_sweeps.add(sweep)
        row = dict(raw)
        row["information_gain_per_cost"] = information_gain / (1.0 + falsification_cost)
        rows.append(row)
    rows.sort(key=lambda item: (-item["information_gain_per_cost"], str(item["experiment_id"])))
    return {
        "status": "PROVEN" if rows else "UNMEASURABLE",
        "selected": rows[:limit],
        "candidate_count": len(rows),
        "repeat_sweeps_removed": len(seen_sweeps) - len(rows),
        "paper_read_only": True,
        "real_execution": False,
    }


def rank_correction_bottlenecks(
    bottlenecks: Iterable[Mapping[str, Any]], *, limit: int = 10
) -> dict[str, Any]:
    """Rank measured bottlenecks by correction cost and falsifiability only."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    rows: list[dict[str, Any]] = []
    for raw in bottlenecks:
        if not isinstance(raw, Mapping):
            return {"status": "UNMEASURABLE", "reason": "INVALID_BOTTLENECK", "paper_read_only": True}
        name = str(raw.get("name") or "").strip()
        try:
            cost = float(raw.get("correction_cost"))
            priority = float(raw.get("falsification_priority"))
        except (TypeError, ValueError, OverflowError):
            return {"status": "UNMEASURABLE", "reason": "INVALID_COST_OR_PRIORITY", "paper_read_only": True}
        if not name or not math.isfinite(cost) or cost < 0 or not math.isfinite(priority) or priority < 0:
            return {"status": "UNMEASURABLE", "reason": "INVALID_BOTTLENECK_FIELDS", "paper_read_only": True}
        rows.append({"name": name, "correction_cost": cost, "falsification_priority": priority})
    rows.sort(key=lambda row: (-row["falsification_priority"], row["correction_cost"], row["name"]))
    return {
        "status": "PROVEN" if rows else "UNMEASURABLE",
        "bottlenecks": rows[:limit],
        "candidate_count": len(rows),
        "future_gain_used": False,
        "paper_read_only": True,
        "real_execution": False,
    }


@dataclass(frozen=True, slots=True)
class HistoricalTrade:
    trade_id: str
    session_id: str
    source_path: str
    opened_at_ms: int
    closed_at_ms: int
    coin: str
    side: str
    strategy: str
    exit_method: str
    notional_usdt: float
    entry_price: float
    exit_price: float
    gross_pnl_usdc: float
    net_pnl_usdc: float
    fees_reported_usdc: float
    edge_remaining_bps: float | None
    signal_age_ms: int | None
    consensus_wallets: int | None
    copy_degradation_bps: float | None
    liquidity_score: float | None
    leader_score: float | None
    reconciliation_error_usdc: float
    eligible_for_learning: bool
    exclusion_reasons: tuple[str, ...]
    reported_gross_pnl_usdc: float | None = None
    reported_net_pnl_usdc: float | None = None
    recomputed_gross_pnl_usdc: float | None = None
    recomputed_net_pnl_usdc: float | None = None
    net_reconciliation_error_usdc: float | None = None
    accounting_measurable: bool = True
    accounting_schema_version: str | None = ACCOUNTING_SCHEMA_VERSION
    strict_accounting_eligible: bool = True


@dataclass(frozen=True, slots=True)
class RuleSpec:
    key: str
    description: str
    clauses: tuple[tuple[str, str, object], ...]
    learned_from_train: bool = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_float(value: Any) -> float | None:
    return finite_number(value)


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _event_timestamp_ms(row: dict[str, Any]) -> int:
    parsed = _to_int(
        first_not_none(
            row.get("timestamp_ms"),
            row.get("observed_at_ms"),
            row.get("recorded_at_ms"),
            row.get("closed_at_ms"),
        )
    )
    return 0 if parsed is None else parsed


def _wallet_count(row: dict[str, Any]) -> int | None:
    explicit = _to_int(
        first_not_none(row.get("consensus_wallets"), row.get("wallet_count"))
    )
    if explicit is not None:
        return max(0, explicit)
    wallets = str(row.get("wallet_address") or row.get("leader_wallet") or "")
    distinct = {part.strip().lower() for part in wallets.split(",") if part.strip()}
    return len(distinct) or None


def _first_float(row: dict[str, Any], *keys: str) -> float | None:
    return _to_float(first_not_none(*(row.get(key) for key in keys)))


def _first_int(row: dict[str, Any], *keys: str) -> int | None:
    return _to_int(first_not_none(*(row.get(key) for key in keys)))


def _first_float_across(
    *candidates: tuple[dict[str, Any], tuple[str, ...]],
) -> float | None:
    values: list[Any] = []
    for row, keys in candidates:
        values.extend(row.get(key) for key in keys)
    return _to_float(first_not_none(*values))


def _position_instance_id(row: dict[str, Any]) -> str:
    value = first_not_none(
        row.get("paper_position_instance_id"),
        row.get("position_instance_id"),
        row.get("matched_position_key"),
    )
    return "" if value is None else str(value).strip()


def _event_identity(row: dict[str, Any], line_number: int) -> str:
    explicit = first_not_none(
        row.get("dedupe_identity"),
        row.get("paper_position_instance_id"),
        row.get("v9_paper_order_id"),
        row.get("delta_key"),
        row.get("evidence_hash"),
    )
    action = first_not_none(row.get("paper_action_type"), row.get("event_type"))
    identity = line_number if explicit is None else explicit
    return "|".join(
        "" if part is None else str(part)
        for part in (
            action,
            identity,
            _event_timestamp_ms(row),
            row.get("coin"),
            row.get("estimated_net_pnl_usdc"),
        )
    )


def _strategy_name(open_row: dict[str, Any]) -> str:
    text = " ".join(
        str(open_row.get(key) or "")
        for key in ("strategy_mode", "strategie", "bot_decision", "reason", "leader_action")
    ).upper()
    if "FUNDING" in text:
        return "FUNDING"
    if "ARBITRAGE" in text or "ARB_" in text:
        return "ARBITRAGE"
    if "FUSION" in text:
        return "FUSION"
    if "CONSENSUS" in text:
        return "CONSENSUS"
    if "COPY" in text or "LEADER" in text:
        return "COPY"
    return "LEGACY_OR_UNKNOWN"


def _accounting_schema(
    open_row: dict[str, Any],
    close_row: dict[str, Any],
) -> str | None:
    value = first_not_none(
        close_row.get("accounting_schema_version"),
        open_row.get("accounting_schema_version"),
    )
    return None if value is None else str(value).strip() or None


def _entry_cost_usdc(open_row: dict[str, Any]) -> float | None:
    if open_row.get("fee_already_embedded_in_entry_price") is True:
        return 0.0
    return _first_float(
        open_row,
        "entry_cost_usdc",
        "entry_costs_usdc",
        "entry_costs",
        "fee_cost_usdc",
        "fee_paid",
    )


def _exit_cost_usdc(close_row: dict[str, Any]) -> float | None:
    if close_row.get("fee_already_embedded_in_exit_price") is True:
        return 0.0
    return _first_float(
        close_row,
        "exit_cost_usdc",
        "exit_costs_usdc",
        "exit_costs",
        "fee_cost_usdc",
        "fee_paid",
    )


def _funding_cost_usdc(
    open_row: dict[str, Any],
    close_row: dict[str, Any],
) -> float | None:
    explicit_cost = _first_float_across(
        (close_row, ("funding_cost_usdc",)),
        (open_row, ("funding_cost_usdc",)),
    )
    if explicit_cost is not None:
        return explicit_cost
    signed_pnl = _first_float_across(
        (close_row, ("funding_pnl_usdc", "funding_net_usdc")),
        (open_row, ("funding_pnl_usdc", "funding_net_usdc")),
    )
    return None if signed_pnl is None else -signed_pnl


def _contamination_reasons(
    open_row: dict[str, Any],
    close_row: dict[str, Any],
) -> list[str]:
    combined = {**open_row, **close_row}
    reasons: list[str] = []
    origin_text = " ".join(
        str(combined.get(key) or "").upper()
        for key in (
            "data_origin",
            "source_kind",
            "execution_source",
            "execution_truth_mode",
            "price_source",
            "book_source",
        )
    )
    if any(token in origin_text for token in ("SYNTHETIC", "FAKE", "DEMO")):
        reasons.append("SYNTHETIC_OR_FAKE_DATA")
    if any(
        combined.get(key) is True
        for key in (
            "maker_fill_assumed",
            "assumed_full_fill",
            "fictitious_depth",
            "synthetic_depth",
        )
    ):
        reasons.append("UNEVIDENCED_EXECUTION_ASSUMPTION")
    if (
        "MID" in origin_text
        and _first_float(close_row, "exit_executable_price") is None
        and _first_float(open_row, "entry_executable_price") is None
    ):
        reasons.append("MID_PRICE_NOT_EXECUTABLE")
    if any(
        combined.get(key) is True
        for key in (
            "cost_defaulted_to_zero",
            "state_reset_detected",
            "double_count_detected",
            "degraded_constant_costs",
        )
    ):
        reasons.append("KNOWN_ACCOUNTING_CONTAMINATION")
    return reasons


def discover_session_ledgers(log_dir: Path) -> tuple[Path, ...]:
    """Return active and archived canonical ledgers in deterministic order."""

    paths: list[Path] = []
    active = log_dir / CANONICAL_LEDGER_NAME
    if active.exists() and active.is_file() and active.stat().st_size > 0:
        paths.append(active)
    archive_root = log_dir / "_archives"
    if archive_root.exists():
        paths.extend(
            path
            for path in archive_root.rglob(CANONICAL_LEDGER_NAME)
            if path.is_file() and path.stat().st_size > 0
        )
    return tuple(sorted(dict.fromkeys(paths), key=lambda path: str(path).lower()))


def _iter_json_rows(path: Path) -> Iterable[tuple[int, dict[str, Any] | None]]:
    try:
        handle = path.open("r", encoding="utf-8-sig", errors="replace")
    except OSError:
        return
    with handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                yield line_number, None
                continue
            yield line_number, payload if isinstance(payload, dict) else None


def _build_trade(
    *,
    session_id: str,
    source_path: Path,
    open_row: dict[str, Any],
    close_row: dict[str, Any],
    ordinal: int,
) -> HistoricalTrade:
    coin = str(close_row.get("coin") or open_row.get("coin") or "?").upper()
    side = str(open_row.get("leader_side") or close_row.get("leader_side") or "").upper()
    opened_at_ms = _event_timestamp_ms(open_row)
    closed_at_ms = _event_timestamp_ms(close_row)
    entry_price_value = _first_float_across(
        (open_row, ("entry_executable_price", "fill_price", "entry_price", "average_entry_price")),
        (close_row, ("average_entry_price", "entry_executable_price", "entry_price")),
    )
    exit_price_value = _first_float(
        close_row,
        "exit_executable_price",
        "fill_price",
        "exit_price",
        "leader_price",
    )
    quantity = _first_float_across(
        (close_row, ("filled_quantity", "closed_quantity", "quantity", "size_closed")),
        (open_row, ("filled_quantity", "quantity", "size")),
    )
    if quantity is not None:
        quantity = abs(quantity)
    explicit_notional = _first_float_across(
        (close_row, ("notional_closed_usdt", "notional_usdt")),
        (
            open_row,
            (
                "copied_notional_usdt",
                "v9_paper_notional_usdc",
                "leader_notional_usdc",
                "notional_usdt",
            ),
        ),
    )
    reported_gross = _first_float(close_row, "gross_pnl_usdc", "gross_pnl")
    reported_net = _first_float(
        close_row,
        "estimated_net_pnl_usdc",
        "event_net_pnl_usdc",
        "net_pnl",
    )
    entry_cost = _entry_cost_usdc(open_row)
    exit_cost = _exit_cost_usdc(close_row)
    funding_cost = _funding_cost_usdc(open_row, close_row)

    recomputed_gross: float | None = None
    if (
        entry_price_value is not None
        and entry_price_value > 0
        and exit_price_value is not None
        and exit_price_value > 0
        and quantity is not None
        and quantity > 0
        and side in {"LONG", "SHORT"}
    ):
        move = exit_price_value - entry_price_value
        recomputed_gross = quantity * (move if side == "LONG" else -move)
    recomputed_net = round_trip_net_pnl_usdc(
        gross_pnl_usdc=recomputed_gross,
        entry_cost_usdc=entry_cost,
        exit_cost_usdc=exit_cost,
        funding_cost_usdc=funding_cost,
    )
    notional_value = explicit_notional
    if (
        notional_value is None
        and quantity is not None
        and quantity > 0
        and entry_price_value is not None
        and entry_price_value > 0
    ):
        notional_value = quantity * entry_price_value

    gross_error = (
        recomputed_gross - reported_gross
        if recomputed_gross is not None and reported_gross is not None
        else None
    )
    net_error = (
        recomputed_net - reported_net
        if recomputed_net is not None and reported_net is not None
        else None
    )

    exit_method = str(close_row.get("exit_method") or close_row.get("reason") or "UNKNOWN").upper()
    reasons: list[str] = []
    reasons.extend(_contamination_reasons(open_row, close_row))
    if LEGACY_UNEVIDENCED_MARKER in exit_method:
        reasons.append("LEGACY_UNEVIDENCED_EXIT")
    schema = _accounting_schema(open_row, close_row)
    if schema != ACCOUNTING_SCHEMA_VERSION:
        reasons.append("HISTORICAL_ACCOUNTING_SCHEMA_UNVERIFIED")
    if side not in {"LONG", "SHORT"}:
        reasons.append("SIDE_UNKNOWN")
    if (
        entry_price_value is None
        or entry_price_value <= 0
        or exit_price_value is None
        or exit_price_value <= 0
    ):
        reasons.append("EXECUTABLE_PRICE_MISSING")
    if quantity is None or quantity <= 0:
        reasons.append("FILLED_QUANTITY_MISSING")
    if notional_value is None or notional_value <= 0:
        reasons.append("NOTIONAL_MISSING")
    if entry_cost is None or exit_cost is None or funding_cost is None:
        reasons.append("ROUND_TRIP_COST_UNMEASURABLE")
    if reported_gross is None:
        reasons.append("LEDGER_REPORTED_GROSS_MISSING")
    if reported_net is None:
        reasons.append("LEDGER_REPORTED_NET_MISSING")
    if opened_at_ms <= 0 or closed_at_ms <= opened_at_ms:
        reasons.append("TIMESTAMP_INVALID")
    gross_reference = 0.0 if reported_gross is None else reported_gross
    net_reference = 0.0 if reported_net is None else reported_net
    gross_tolerance = max(0.000001, abs(gross_reference) * 0.0001)
    net_tolerance = max(0.000001, abs(net_reference) * 0.0001)
    if gross_error is not None and abs(gross_error) > gross_tolerance:
        reasons.append("GROSS_PNL_RECONCILIATION_MISMATCH")
    if net_error is not None and abs(net_error) > net_tolerance:
        reasons.append("NET_PNL_RECONCILIATION_MISMATCH")
    if recomputed_net is None:
        reasons.append("PNL_UNMEASURABLE")

    position_key = _position_instance_id(close_row) or _position_instance_id(open_row)
    trade_id = f"{session_id}|{position_key}|{opened_at_ms}|{closed_at_ms}|{ordinal}"
    accounting_measurable = recomputed_gross is not None and recomputed_net is not None
    return HistoricalTrade(
        trade_id=trade_id,
        session_id=session_id,
        source_path=str(source_path),
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
        coin=coin,
        side=side,
        strategy=_strategy_name(open_row),
        exit_method=exit_method,
        notional_usdt=0.0 if notional_value is None else notional_value,
        entry_price=0.0 if entry_price_value is None else entry_price_value,
        exit_price=0.0 if exit_price_value is None else exit_price_value,
        gross_pnl_usdc=0.0 if recomputed_gross is None else recomputed_gross,
        net_pnl_usdc=0.0 if recomputed_net is None else recomputed_net,
        fees_reported_usdc=(
            0.0
            if entry_cost is None or exit_cost is None
            else entry_cost + exit_cost
        ),
        edge_remaining_bps=_to_float(
            first_not_none(
                open_row.get("edge_remaining_bps"),
                open_row.get("v9_edge_remaining_bps_after_market"),
            )
        ),
        signal_age_ms=_to_int(open_row.get("signal_age_ms")),
        consensus_wallets=_wallet_count(open_row),
        copy_degradation_bps=_to_float(open_row.get("copy_degradation_bps")),
        liquidity_score=_to_float(
            first_not_none(
                open_row.get("liquidity_score"),
                open_row.get("v9_liquidity_score"),
            )
        ),
        leader_score=_to_float(open_row.get("leader_score")),
        reconciliation_error_usdc=0.0 if gross_error is None else gross_error,
        eligible_for_learning=not reasons,
        exclusion_reasons=tuple(dict.fromkeys(reasons)),
        reported_gross_pnl_usdc=reported_gross,
        reported_net_pnl_usdc=reported_net,
        recomputed_gross_pnl_usdc=recomputed_gross,
        recomputed_net_pnl_usdc=recomputed_net,
        net_reconciliation_error_usdc=net_error,
        accounting_measurable=accounting_measurable,
        accounting_schema_version=schema,
        strict_accounting_eligible=accounting_measurable and not reasons,
    )


def extract_historical_trades(log_dir: Path) -> tuple[tuple[HistoricalTrade, ...], dict[str, Any]]:
    """Read stale archives explicitly and pair canonical OPEN/CLOSE events."""

    trades: list[HistoricalTrade] = []
    quality: dict[str, Any] = {
        "ledger_files": 0,
        "json_errors": 0,
        "duplicate_events": 0,
        "open_events": 0,
        "close_events": 0,
        "paired_round_trips": 0,
        "orphan_closes": 0,
        "still_open": 0,
        "open_events_missing_position_instance": 0,
        "close_events_missing_position_instance": 0,
        "duplicate_position_instances": 0,
        "ambiguous_position_events": 0,
        "non_monotonic_events": 0,
        "ignored_non_pnl_rows": 0,
    }
    for path in discover_session_ledgers(log_dir):
        quality["ledger_files"] += 1
        session_id = path.parent.name if path.parent != log_dir else "active"
        open_by_instance: dict[str, dict[str, Any]] = {}
        ambiguous_instances: set[str] = set()
        seen: set[str] = set()
        previous_timestamp = 0
        for line_number, row in _iter_json_rows(path):
            if row is None:
                quality["json_errors"] += 1
                continue
            identity = _event_identity(row, line_number)
            if identity in seen:
                quality["duplicate_events"] += 1
                continue
            seen.add(identity)
            timestamp = _event_timestamp_ms(row)
            if timestamp and previous_timestamp and timestamp < previous_timestamp:
                quality["non_monotonic_events"] += 1
            if timestamp:
                previous_timestamp = max(previous_timestamp, timestamp)

            action = str(row.get("paper_action_type") or row.get("event_type") or "").upper()
            if action == "OPEN":
                quality["open_events"] += 1
                instance_id = _position_instance_id(row)
                if not instance_id:
                    quality["open_events_missing_position_instance"] += 1
                    quality["ambiguous_position_events"] += 1
                    continue
                if instance_id in open_by_instance or instance_id in ambiguous_instances:
                    open_by_instance.pop(instance_id, None)
                    ambiguous_instances.add(instance_id)
                    quality["duplicate_position_instances"] += 1
                    quality["ambiguous_position_events"] += 1
                    continue
                open_by_instance[instance_id] = row
                continue
            if action != "CLOSE":
                quality["ignored_non_pnl_rows"] += 1
                continue
            quality["close_events"] += 1
            instance_id = _position_instance_id(row)
            if not instance_id:
                quality["close_events_missing_position_instance"] += 1
                quality["ambiguous_position_events"] += 1
                continue
            if instance_id in ambiguous_instances:
                quality["ambiguous_position_events"] += 1
                continue
            open_row = open_by_instance.pop(instance_id, None)
            if open_row is None:
                quality["orphan_closes"] += 1
                continue
            trades.append(
                _build_trade(
                    session_id=session_id,
                    source_path=path,
                    open_row=open_row,
                    close_row=row,
                    ordinal=len(trades) + 1,
                )
            )
        quality["still_open"] += len(open_by_instance)

    quality["paired_round_trips"] = len(trades)
    quality["eligible_round_trips"] = sum(trade.eligible_for_learning for trade in trades)
    quality["excluded_round_trips"] = len(trades) - quality["eligible_round_trips"]
    quality["contaminated_round_trips"] = sum(
        not trade.accounting_measurable
        or trade.accounting_schema_version != ACCOUNTING_SCHEMA_VERSION
        or any(
            reason
            in {
                "SYNTHETIC_OR_FAKE_DATA",
                "UNEVIDENCED_EXECUTION_ASSUMPTION",
                "MID_PRICE_NOT_EXECUTABLE",
                "KNOWN_ACCOUNTING_CONTAMINATION",
                "HISTORICAL_ACCOUNTING_SCHEMA_UNVERIFIED",
            }
            for reason in trade.exclusion_reasons
        )
        for trade in trades
    )
    quality["strict_history_status"] = (
        "BLOCKED_CORRUPT_JSON"
        if quality["json_errors"]
        else (
            "PARTIAL_CONTAMINATED"
            if quality["contaminated_round_trips"]
            or quality["ambiguous_position_events"]
            else "STRICT_RECONCILED"
        )
    )
    exclusion_counts: defaultdict[str, int] = defaultdict(int)
    for trade in trades:
        for reason in trade.exclusion_reasons:
            exclusion_counts[reason] += 1
    quality["exclusion_reasons"] = dict(sorted(exclusion_counts.items()))
    return tuple(sorted(trades, key=lambda trade: (trade.opened_at_ms, trade.trade_id))), quality


def _profit_factor(gains: float, losses: float) -> float | None:
    if losses <= 0:
        return None if gains <= 0 else 999.0
    return gains / losses


def compute_metrics(
    trades: Sequence[HistoricalTrade],
    *,
    comparison_notional_usdt: float = DEFAULT_COMPARISON_NOTIONAL_USDT,
) -> dict[str, Any]:
    source_rows = list(trades)
    ordered = sorted(
        (
            trade
            for trade in source_rows
            if trade.accounting_measurable and trade.strict_accounting_eligible
        ),
        key=lambda trade: (trade.closed_at_ms, trade.trade_id),
    )
    actual_values = [trade.net_pnl_usdc for trade in ordered]
    normalized_values = [
        (
            trade.net_pnl_usdc / trade.notional_usdt * comparison_notional_usdt
            if trade.notional_usdt > 0
            else 0.0
        )
        for trade in ordered
    ]
    gains = sum(value for value in actual_values if value > 0)
    losses = abs(sum(value for value in actual_values if value < 0))
    normalized_gains = sum(value for value in normalized_values if value > 0)
    normalized_losses = abs(sum(value for value in normalized_values if value < 0))
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in normalized_values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    gross_abs = sum(abs(trade.gross_pnl_usdc) for trade in ordered)
    return {
        "input_trades": len(source_rows),
        "unmeasurable_trades": sum(
            not trade.accounting_measurable for trade in source_rows
        ),
        "strict_excluded_trades": len(source_rows) - len(ordered),
        "trades": len(ordered),
        "sessions": len({trade.session_id for trade in ordered}),
        "net_pnl_actual_usdc": round(sum(actual_values), 8),
        "gross_pnl_actual_usdc": round(sum(trade.gross_pnl_usdc for trade in ordered), 8),
        "fees_reported_usdc": round(sum(trade.fees_reported_usdc for trade in ordered), 8),
        "fee_drag_over_abs_gross": round(sum(trade.fees_reported_usdc for trade in ordered) / gross_abs, 8)
        if gross_abs > 0
        else None,
        "profit_factor_actual": (
            round(value, 8) if (value := _profit_factor(gains, losses)) is not None else None
        ),
        "win_rate": round(sum(value > 0 for value in actual_values) / len(actual_values), 8)
        if actual_values
        else None,
        "average_win_usdc": round(gains / sum(value > 0 for value in actual_values), 8)
        if any(value > 0 for value in actual_values)
        else None,
        "average_loss_usdc": round(
            losses / sum(value < 0 for value in actual_values), 8
        )
        if any(value < 0 for value in actual_values)
        else None,
        "comparison_notional_usdt": comparison_notional_usdt,
        "normalized_net_usdc": round(sum(normalized_values), 8),
        "linear_notional_projection_status": "RESEARCH_ONLY_NONLINEAR_DEPTH_UNPROVEN",
        "capacity_promotable_from_linear_projection": False,
        "profit_factor_normalized": (
            round(value, 8)
            if (value := _profit_factor(normalized_gains, normalized_losses)) is not None
            else None
        ),
        "max_drawdown_normalized_usdc": round(max_drawdown, 8),
        "median_normalized_trade_usdc": round(median(normalized_values), 8)
        if normalized_values
        else None,
    }


def _field_value(trade: HistoricalTrade, field: str) -> object:
    return getattr(trade, field)


def rule_matches(trade: HistoricalTrade, rule: RuleSpec) -> bool:
    for field, operator, target in rule.clauses:
        value = _field_value(trade, field)
        if operator == "eq" and value != target:
            return False
        if operator == "ge" and (value is None or float(value) < float(target)):
            return False
        if operator == "le" and (value is None or float(value) > float(target)):
            return False
        if operator == "not_in" and value in set(target if isinstance(target, tuple) else (target,)):
            return False
    return True


def _feature_coverage(trades: Sequence[HistoricalTrade]) -> dict[str, dict[str, float | int]]:
    fields = (
        "edge_remaining_bps",
        "signal_age_ms",
        "consensus_wallets",
        "copy_degradation_bps",
        "liquidity_score",
        "leader_score",
    )
    total = len(trades)
    return {
        field: {
            "present": sum(_field_value(trade, field) is not None for trade in trades),
            "total": total,
            "ratio": round(
                sum(_field_value(trade, field) is not None for trade in trades) / total, 6
            )
            if total
            else 0.0,
        }
        for field in fields
    }


def build_candidate_rules(train: Sequence[HistoricalTrade]) -> tuple[RuleSpec, ...]:
    """Build deterministic rules using train data only."""

    rules: list[RuleSpec] = [
        RuleSpec("baseline_all", "Toutes les entrees eligibles", ()),
        RuleSpec("side_long", "Sens LONG uniquement", (("side", "eq", "LONG"),)),
        RuleSpec("side_short", "Sens SHORT uniquement", (("side", "eq", "SHORT"),)),
    ]
    for minimum in (2, 3, 4):
        rules.append(
            RuleSpec(
                f"consensus_ge_{minimum}",
                f"Consensus d'au moins {minimum} wallets",
                (("consensus_wallets", "ge", minimum),),
            )
        )

    coverage = _feature_coverage(train)
    minimum_coverage = max(8, int(len(train) * 0.35))
    if coverage["edge_remaining_bps"]["present"] >= minimum_coverage:
        for threshold in (10.0, 20.0, 30.0, 40.0, 50.0):
            rules.append(
                RuleSpec(
                    f"edge_ge_{threshold:g}",
                    f"Edge restant >= {threshold:g} bps",
                    (("edge_remaining_bps", "ge", threshold),),
                )
            )
    if coverage["signal_age_ms"]["present"] >= minimum_coverage:
        for threshold in (1_000, 2_000, 4_000, 8_000):
            rules.append(
                RuleSpec(
                    f"age_le_{threshold}",
                    f"Age du signal <= {threshold} ms",
                    (("signal_age_ms", "le", threshold),),
                )
            )
    if coverage["copy_degradation_bps"]["present"] >= minimum_coverage:
        for threshold in (10.0, 20.0, 30.0):
            rules.append(
                RuleSpec(
                    f"degradation_le_{threshold:g}",
                    f"Degradation de copie <= {threshold:g} bps",
                    (("copy_degradation_bps", "le", threshold),),
                )
            )
    if coverage["liquidity_score"]["present"] >= minimum_coverage:
        for threshold in (0.5, 0.65, 0.8):
            rules.append(
                RuleSpec(
                    f"liquidity_ge_{threshold:g}",
                    f"Liquidite >= {threshold:g}",
                    (("liquidity_score", "ge", threshold),),
                )
            )

    strategy_counts: defaultdict[str, int] = defaultdict(int)
    for trade in train:
        strategy_counts[trade.strategy] += 1
    for strategy, count in sorted(strategy_counts.items()):
        if count >= 5:
            rules.append(
                RuleSpec(
                    f"strategy_{strategy.lower()}",
                    f"Strategie {strategy} uniquement",
                    (("strategy", "eq", strategy),),
                )
            )

    by_coin: defaultdict[str, list[HistoricalTrade]] = defaultdict(list)
    for trade in train:
        by_coin[trade.coin].append(trade)
    losing_coins = sorted(
        (
            (compute_metrics(rows)["normalized_net_usdc"], coin)
            for coin, rows in by_coin.items()
            if len(rows) >= MIN_COIN_BLACKLIST_TRADES
            and len({row.session_id for row in rows}) >= MIN_COIN_BLACKLIST_TIME_SLICES
            and compute_metrics(rows)["net_pnl_actual_usdc"] < 0
        ),
        key=lambda item: (item[0], item[1]),
    )
    for count in (1, 3, 5):
        excluded = tuple(coin for _net, coin in losing_coins[:count])
        if len(excluded) == count:
            rules.append(
                RuleSpec(
                    f"exclude_train_losers_{count}",
                    "Exclure les coins perdants appris sur train: " + ", ".join(excluded),
                    (("coin", "not_in", excluded),),
                    learned_from_train=True,
                )
            )

    unique: dict[str, RuleSpec] = {}
    for rule in rules:
        unique.setdefault(rule.key, rule)
    return tuple(unique.values())


def _pf_for_gate(metrics: dict[str, Any]) -> float:
    value = metrics.get("profit_factor_actual")
    return float(value) if value is not None else 0.0


def _purged_three_way_split(
    eligible: Sequence[HistoricalTrade],
    *,
    embargo_ms: int,
) -> tuple[list[HistoricalTrade], list[HistoricalTrade], list[HistoricalTrade], dict[str, int]]:
    train_end = max(1, int(len(eligible) * 0.60))
    validation_end = max(train_end + 1, int(len(eligible) * 0.80))
    validation_end = min(validation_end, len(eligible) - 1)
    validation_start_ms = eligible[train_end].opened_at_ms
    holdout_start_ms = eligible[validation_end].opened_at_ms
    train_raw = eligible[:train_end]
    validation_raw = eligible[train_end:validation_end]
    holdout_raw = eligible[validation_end:]
    train = [trade for trade in train_raw if trade.closed_at_ms < validation_start_ms]
    validation = [
        trade
        for trade in validation_raw
        if trade.opened_at_ms >= validation_start_ms + embargo_ms
        and trade.closed_at_ms < holdout_start_ms
    ]
    holdout = [
        trade for trade in holdout_raw if trade.opened_at_ms >= holdout_start_ms + embargo_ms
    ]
    audit = {
        "embargo_ms": int(embargo_ms),
        "purged_train": len(train_raw) - len(train),
        "purged_validation": len(validation_raw) - len(validation),
        "purged_holdout": len(holdout_raw) - len(holdout),
    }
    return train, validation, holdout, audit


def _research_objective(metrics: dict[str, Any]) -> float:
    pf = _pf_for_gate(metrics)
    net = float(metrics.get("net_pnl_actual_usdc") or 0.0)
    drawdown = float(metrics.get("max_drawdown_normalized_usdc") or 0.0)
    return max(-10.0, min(10.0, pf)) + (net / (1.0 + drawdown))


def evaluate_candidate_rules(
    trades: Sequence[HistoricalTrade],
    *,
    comparison_notional_usdt: float = DEFAULT_COMPARISON_NOTIONAL_USDT,
    min_total_trades: int = MIN_TOTAL_TRADES,
    embargo_ms: int = 1_000,
) -> dict[str, Any]:
    """Chronological train/validation selection followed by untouched holdout."""

    eligible = sorted(
        (trade for trade in trades if trade.eligible_for_learning),
        key=lambda trade: (trade.opened_at_ms, trade.trade_id),
    )
    if len(eligible) < min_total_trades:
        return {
            "status": "INSUFFICIENT_DATA",
            "reason": f"{len(eligible)} trades eligibles; minimum {min_total_trades}.",
            "eligible_trades": len(eligible),
            "automatic_activation": False,
            "candidates": [],
        }

    train, validation, holdout, split_audit = _purged_three_way_split(
        eligible,
        embargo_ms=max(0, int(embargo_ms)),
    )
    rules = build_candidate_rules(train)
    minimum_train = max(6, int(len(train) * 0.20))
    minimum_validation = max(3, int(len(validation) * 0.25))
    minimum_holdout = max(3, int(len(holdout) * 0.25))
    baseline = {
        "train": compute_metrics(train, comparison_notional_usdt=comparison_notional_usdt),
        "validation": compute_metrics(
            validation, comparison_notional_usdt=comparison_notional_usdt
        ),
        "holdout": compute_metrics(holdout, comparison_notional_usdt=comparison_notional_usdt),
    }

    candidates: list[dict[str, Any]] = []
    for rule in rules:
        subsets = {
            "train": [trade for trade in train if rule_matches(trade, rule)],
            "validation": [trade for trade in validation if rule_matches(trade, rule)],
            "holdout": [trade for trade in holdout if rule_matches(trade, rule)],
        }
        metrics = {
            split: compute_metrics(rows, comparison_notional_usdt=comparison_notional_usdt)
            for split, rows in subsets.items()
        }
        selected_before_holdout = (
            rule.key != "baseline_all"
            and metrics["train"]["trades"] >= minimum_train
            and metrics["validation"]["trades"] >= minimum_validation
            and metrics["train"]["net_pnl_actual_usdc"] > 0
            and metrics["validation"]["net_pnl_actual_usdc"] > 0
            and _pf_for_gate(metrics["train"]) >= 1.0
            and _pf_for_gate(metrics["validation"]) >= 1.05
        )
        if not selected_before_holdout:
            verdict = "REJECTED_SELECTION"
        elif metrics["holdout"]["trades"] < minimum_holdout:
            verdict = "INSUFFICIENT_HOLDOUT"
        elif (
            metrics["holdout"]["net_pnl_actual_usdc"] > 0
            and _pf_for_gate(metrics["holdout"]) >= 1.0
        ):
            verdict = "HYPOTHESIS_HOLDOUT_PASSED"
        else:
            verdict = "FAILED_HOLDOUT"
        selection_score = min(
            _research_objective(metrics["train"]),
            _research_objective(metrics["validation"]),
        )
        candidates.append(
            {
                "key": rule.key,
                "description": rule.description,
                "clauses": [list(clause) for clause in rule.clauses],
                "learned_from_train": rule.learned_from_train,
                "selected_before_holdout": selected_before_holdout,
                "selection_score_train_validation_only": round(selection_score, 8),
                "verdict": verdict,
                "promotion_eligible": False,
                "requires_forward_paper_post_freeze": True,
                "metrics": metrics,
            }
        )

    candidates.sort(
        key=lambda item: (
            item["verdict"] != "HYPOTHESIS_HOLDOUT_PASSED",
            item["verdict"] != "INSUFFICIENT_HOLDOUT",
            -float(item["selection_score_train_validation_only"]),
            item["key"],
        )
    )
    return {
        "status": "COMPLETED",
        "eligible_trades": len(eligible),
        "split": {
            "train": len(train),
            "validation": len(validation),
            "holdout": len(holdout),
            **split_audit,
        },
        "validation_stage": "HISTORICAL_HOLDOUT_HYPOTHESIS_ONLY",
        "promotion_eligible": False,
        "selection_uses_holdout": False,
        "automatic_activation": False,
        "comparison_notional_usdt": comparison_notional_usdt,
        "multiple_testing_warning": (
            f"{len(rules)} hypotheses testees; aucune promotion sans replay exact supplementaire."
        ),
        "baseline": baseline,
        "candidates": candidates,
    }


def _group_metrics(
    trades: Sequence[HistoricalTrade],
    getter: Callable[[HistoricalTrade], str],
    *,
    comparison_notional_usdt: float,
) -> list[dict[str, Any]]:
    grouped: defaultdict[str, list[HistoricalTrade]] = defaultdict(list)
    for trade in trades:
        grouped[getter(trade)].append(trade)
    rows = [
        {
            "group": group,
            **compute_metrics(values, comparison_notional_usdt=comparison_notional_usdt),
        }
        for group, values in grouped.items()
    ]
    return sorted(
        rows,
        key=lambda row: (float(row["normalized_net_usdc"]), str(row["group"])),
    )


def _build_findings(
    trades: Sequence[HistoricalTrade],
    quality: dict[str, Any],
    validation: dict[str, Any],
    groups: dict[str, list[dict[str, Any]]],
) -> dict[str, list[str]]:
    eligible = [trade for trade in trades if trade.eligible_for_learning]
    metrics = compute_metrics(eligible)
    robust = [
        item["description"]
        for item in validation.get("candidates", [])
        if item.get("verdict") == "HYPOTHESIS_HOLDOUT_PASSED"
    ]
    confirm = [
        item["description"]
        for item in validation.get("candidates", [])
        if item.get("verdict") == "INSUFFICIENT_HOLDOUT"
    ][:8]
    rejected = [
        f"{item['description']} ({item['verdict']})"
        for item in validation.get("candidates", [])
        if item.get("verdict") in {"FAILED_HOLDOUT", "REJECTED_SELECTION"}
        and item.get("key") != "baseline_all"
    ][:12]
    missing: list[str] = []
    coverage = _feature_coverage(eligible)
    for field, detail in coverage.items():
        if float(detail["ratio"]) < 0.80:
            missing.append(
                f"{field}: {detail['present']}/{detail['total']} trades ({float(detail['ratio']):.1%})."
            )
    if quality.get("orphan_closes"):
        missing.append(
            f"{quality['orphan_closes']} clotures sans OPEN canonique dans la meme session."
        )
    if quality.get("excluded_round_trips"):
        missing.append(
            f"{quality['excluded_round_trips']} round-trips exclus de l'apprentissage: "
            f"{quality.get('exclusion_reasons', {})}."
        )

    experiments: list[str] = []
    exit_rows = {row["group"]: row for row in groups.get("by_exit_method", [])}
    stop = exit_rows.get("SLTP_STOP_LOSS")
    timeout = exit_rows.get("SLTP_TIMEOUT")
    take_profit = exit_rows.get("SLTP_TAKE_PROFIT")
    if stop and float(stop["net_pnl_actual_usdc"]) < 0:
        experiments.append(
            "A/B exact SL/TP a risque et notionnel constants: le STOP_LOSS concentre "
            f"{stop['net_pnl_actual_usdc']:.2f} USDC sur {stop['trades']} sorties."
        )
    if timeout and float(timeout["net_pnl_actual_usdc"]) < 0:
        experiments.append(
            "A/B de duree maximale sur marks reels: les TIMEOUT cumulent "
            f"{timeout['net_pnl_actual_usdc']:.2f} USDC sur {timeout['trades']} sorties."
        )
    if not take_profit or int(take_profit["trades"]) < 5:
        experiments.append(
            "Verifier le cablage TAKE_PROFIT: moins de 5 sorties TP appariables, "
            "donc l'asymetrie TP/SL n'est pas validable."
        )
    if metrics.get("fee_drag_over_abs_gross") and float(metrics["fee_drag_over_abs_gross"]) > 0.20:
        experiments.append(
            "Rejouer un plancher d'edge net couvrant le cout aller-retour; "
            f"drag de frais observe {float(metrics['fee_drag_over_abs_gross']):.1%}."
        )
    experiments.append(
        "Promouvoir un flag uniquement si PF net > 1 sur validation ET holdout, "
        "puis sur un replay exact sans lookahead."
    )
    return {
        "robust_opportunities": robust,
        "needs_confirmation": confirm,
        "rejected_hypotheses": rejected,
        "missing_evidence": missing,
        "next_exact_ab_experiments": experiments,
    }


def _build_experiment_backlog(
    trades: Sequence[HistoricalTrade],
    quality: dict[str, Any],
    groups: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Translate measured loss causes into reproducible, non-activating experiments."""

    eligible = [trade for trade in trades if trade.eligible_for_learning]
    metrics = compute_metrics(eligible)
    exits = {row["group"]: row for row in groups.get("by_exit_method", [])}
    experiments: list[dict[str, Any]] = []

    def add(
        experiment_id: str,
        priority: int,
        title: str,
        hypothesis: str,
        evidence: dict[str, Any],
        parameter_grid: dict[str, list[object]],
        required_evidence: list[str],
    ) -> None:
        experiments.append(
            {
                "experiment_id": experiment_id,
                "priority": priority,
                "title": title,
                "hypothesis": hypothesis,
                "evidence": evidence,
                "parameter_grid": parameter_grid,
                "required_evidence": required_evidence,
                "validation_protocol": (
                    "Selection sur train + validation chronologiques; holdout intact; "
                    "replay exact sans lookahead; notionnel constant 50 USDT."
                ),
                "promotion_gates": [
                    "profit_factor_net_validation > 1.0",
                    "profit_factor_net_holdout > 1.0",
                    "net_pnl_holdout > 0",
                    "minimum_30_trades_mesurables",
                    "aucune_regression_data_quality",
                ],
                "automatic_activation": False,
            }
        )

    orphan_closes = int(quality.get("orphan_closes") or 0)
    excluded = int(quality.get("excluded_round_trips") or 0)
    if orphan_closes or excluded:
        add(
            "LEDGER_PAIRING_RECONCILIATION",
            1,
            "Fiabiliser les round-trips canoniques",
            (
                "Une attribution OPEN/CLOSE complete augmente la puissance statistique "
                "et empeche de calibrer le PnL sur un sous-ensemble biaise."
            ),
            {
                "orphan_closes": orphan_closes,
                "excluded_round_trips": excluded,
                "eligible_round_trips": int(quality.get("eligible_round_trips") or 0),
            },
            {},
            [
                "paper_position_instance_id stable",
                "matched_position_key stable",
                "OPEN, REDUCE et CLOSE dans la meme session canonique",
            ],
        )

    stop = exits.get("SLTP_STOP_LOSS")
    if stop and float(stop.get("net_pnl_actual_usdc") or 0.0) < 0:
        add(
            "EXIT_SLTP_GEOMETRY",
            2,
            "Rejouer la geometrie stop-loss / take-profit",
            (
                "Le stop actuel concentre une part importante des pertes; une geometrie "
                "cout-aware peut ameliorer l'esperance sans augmenter le risque nominal."
            ),
            {
                "stop_loss_trades": int(stop.get("trades") or 0),
                "stop_loss_net_usdc": float(stop.get("net_pnl_actual_usdc") or 0.0),
                "stop_loss_fees_usdc": float(stop.get("fees_reported_usdc") or 0.0),
            },
            {
                "stop_loss_bps": [12, 20, 30, 40, 60, 90],
                "take_profit_bps": [20, 30, 45, 60, 90, 120, 180],
                "trailing_bps": [0, 15, 25, 40, 60],
            },
            [
                "marks reels couvrant tout le trade",
                "spread, slippage, fees et latence",
                "sortie explicite TP, SL, trailing ou timeout",
            ],
        )

    timeout = exits.get("SLTP_TIMEOUT")
    if timeout and float(timeout.get("net_pnl_actual_usdc") or 0.0) < 0:
        add(
            "EXIT_TIMEOUT_HORIZON",
            3,
            "Rejouer les horizons de sortie",
            (
                "Les sorties au timeout sont nettes negatives; la duree maximale doit "
                "etre calibree par regime et mesuree apres tous les couts."
            ),
            {
                "timeout_trades": int(timeout.get("trades") or 0),
                "timeout_net_usdc": float(timeout.get("net_pnl_actual_usdc") or 0.0),
                "timeout_fees_usdc": float(timeout.get("fees_reported_usdc") or 0.0),
            },
            {"horizon_minutes": [5, 15, 30, 60, 120, 240]},
            [
                "marks monotones en temps",
                "couverture complete de chaque horizon",
                "regime de volatilite connu a l'entree",
            ],
        )

    fee_drag = float(metrics.get("fee_drag_over_abs_gross") or 0.0)
    if fee_drag > 0.20:
        add(
            "ENTRY_COST_AWARE_EDGE",
            4,
            "Exiger un edge net couvrant le cout aller-retour",
            (
                "Les frais absorbent une part excessive du mouvement brut; augmenter "
                "le nombre de trades sans edge net mesurable aggrave mecaniquement le PnL."
            ),
            {
                "fee_drag_over_abs_gross": fee_drag,
                "fees_reported_usdc": float(metrics.get("fees_reported_usdc") or 0.0),
            },
            {
                "edge_buffer_above_round_trip_cost_bps": [0, 5, 10, 20, 30],
                "comparison_notional_usdt": [50],
            },
            [
                "edge_remaining_bps a l'entree",
                "spread et slippage par coin",
                "fee tier maker/taker",
            ],
        )

    coverage = _feature_coverage(eligible)
    incomplete = {
        field: detail
        for field, detail in coverage.items()
        if float(detail.get("ratio") or 0.0) < 0.80
    }
    if incomplete:
        add(
            "ENTRY_FEATURE_COVERAGE",
            5,
            "Completer les preuves connues a l'entree",
            (
                "Les seuils edge, fraicheur, degradation, liquidite et leader ne peuvent "
                "pas etre calibres proprement tant que leur couverture reste partielle."
            ),
            {"coverage": incomplete},
            {},
            [
                "edge_remaining_bps",
                "signal_age_ms",
                "copy_degradation_bps",
                "liquidity_score",
                "leader_score",
            ],
        )

    recurring_coins = [
        row
        for row in groups.get("by_coin", [])
        if int(row.get("trades") or 0) >= 3
        and float(row.get("normalized_net_usdc") or 0.0) < 0
    ]
    if recurring_coins:
        add(
            "COIN_REGIME_STABILITY",
            6,
            "Tester la stabilite par coin et regime",
            (
                "Les pertes recurrentes doivent etre distinguees d'un accident de regime; "
                "aucune blacklist n'est justifiee par le seul PnL in-sample."
            ),
            {
                "coins": [
                    {
                        "coin": row.get("group"),
                        "trades": int(row.get("trades") or 0),
                        "normalized_net_usdc": float(
                            row.get("normalized_net_usdc") or 0.0
                        ),
                    }
                    for row in recurring_coins[:10]
                ]
            },
            {
                "minimum_coin_sample": [10, 20, 30],
                "minimum_profitable_time_slices": [3, 4],
            },
            [
                "labels de regime sans lookahead",
                "minimum de trades par coin",
                "plusieurs tranches temporelles",
            ],
        )

    return sorted(experiments, key=lambda item: (item["priority"], item["experiment_id"]))


def build_lab_report(
    log_dir: Path,
    *,
    comparison_notional_usdt: float = DEFAULT_COMPARISON_NOTIONAL_USDT,
    min_total_trades: int = MIN_TOTAL_TRADES,
) -> dict[str, Any]:
    trades, quality = extract_historical_trades(log_dir)
    eligible = [trade for trade in trades if trade.eligible_for_learning]
    validation = evaluate_candidate_rules(
        trades,
        comparison_notional_usdt=comparison_notional_usdt,
        min_total_trades=min_total_trades,
    )
    groups = {
        "by_exit_method": _group_metrics(
            eligible,
            lambda trade: trade.exit_method,
            comparison_notional_usdt=comparison_notional_usdt,
        ),
        "by_side": _group_metrics(
            eligible,
            lambda trade: trade.side,
            comparison_notional_usdt=comparison_notional_usdt,
        ),
        "by_strategy": _group_metrics(
            eligible,
            lambda trade: trade.strategy,
            comparison_notional_usdt=comparison_notional_usdt,
        ),
        "by_coin": _group_metrics(
            eligible,
            lambda trade: trade.coin,
            comparison_notional_usdt=comparison_notional_usdt,
        ),
    }
    experiment_backlog = _build_experiment_backlog(trades, quality, groups)
    return {
        "schema_version": 1,
        "generated_at": _utc_now(),
        "source_dir": str(log_dir),
        "local_historical_data_only": True,
        "network_used": False,
        "real_execution": False,
        "automatic_activation": False,
        "comparison_note": (
            "La verite PnL conserve les notionnels paper reels. Les comparaisons de regles "
            f"sont normalisees a {comparison_notional_usdt:g} USDT pour eviter qu'un gros "
            "notionnel domine artificiellement le classement."
        ),
        "quality": quality,
        "truth": {
            "all_paired": compute_metrics(
                trades, comparison_notional_usdt=comparison_notional_usdt
            ),
            "eligible_for_learning": compute_metrics(
                eligible, comparison_notional_usdt=comparison_notional_usdt
            ),
            "feature_coverage": _feature_coverage(eligible),
        },
        "groups": groups,
        "temporal_validation": validation,
        "findings": _build_findings(trades, quality, validation, groups),
        "experiment_backlog": experiment_backlog,
    }


def _markdown_metrics(metrics: dict[str, Any]) -> str:
    pf = metrics.get("profit_factor_actual")
    pf_text = "indisponible" if pf is None else f"{float(pf):.3f}"
    return (
        f"{metrics.get('trades', 0)} trades, net {float(metrics.get('net_pnl_actual_usdc', 0)):.2f} "
        f"USDC, PF {pf_text}, drawdown normalise "
        f"{float(metrics.get('max_drawdown_normalized_usdc', 0)):.2f} USDC"
    )


def _format_pf(value: object) -> str:
    parsed = _to_float(value)
    return "n/a" if parsed is None else f"{parsed:.3f}"


def _group_table(
    title: str,
    rows: Sequence[dict[str, Any]],
    *,
    minimum_trades: int = 1,
    limit: int | None = None,
    reverse: bool = False,
) -> list[str]:
    selected = [
        row for row in rows if int(row.get("trades", 0)) >= minimum_trades
    ]
    selected.sort(
        key=lambda row: (
            float(row.get("normalized_net_usdc", 0.0)),
            str(row.get("group", "")),
        ),
        reverse=reverse,
    )
    if limit is not None:
        selected = selected[:limit]
    lines = [
        f"### {title}",
        "",
        "| Groupe | Trades | Net reel | PF reel | Net normalise | PF normalise | Frais |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    if not selected:
        lines.append("| Aucun groupe mesurable | 0 | 0.00 | n/a | 0.00 | n/a | 0.00 |")
        return lines
    for row in selected:
        lines.append(
            "| "
            f"{row.get('group', 'UNKNOWN')} | "
            f"{int(row.get('trades', 0))} | "
            f"{float(row.get('net_pnl_actual_usdc', 0.0)):.2f} | "
            f"{_format_pf(row.get('profit_factor_actual'))} | "
            f"{float(row.get('normalized_net_usdc', 0.0)):.2f} | "
            f"{_format_pf(row.get('profit_factor_normalized'))} | "
            f"{float(row.get('fees_reported_usdc', 0.0)):.2f} |"
        )
    return lines


def _candidate_table(candidates: Sequence[dict[str, Any]]) -> list[str]:
    lines = [
        "| Hypothese | Train n/PF | Validation n/PF | Holdout n/PF | Verdict |",
        "|---|---:|---:|---:|---|",
    ]
    if not candidates:
        lines.append("| Aucune hypothese mesurable | 0/n/a | 0/n/a | 0/n/a | INSUFFICIENT_DATA |")
        return lines
    ordered = sorted(
        candidates,
        key=lambda row: (
            bool(row.get("selected_before_holdout")),
            float(row.get("selection_score_train_validation_only", 0.0)),
            str(row.get("key", "")),
        ),
        reverse=True,
    )
    for candidate in ordered[:30]:
        metrics = candidate.get("metrics", {})
        split_cells: list[str] = []
        for split in ("train", "validation", "holdout"):
            split_metrics = metrics.get(split, {})
            split_cells.append(
                f"{int(split_metrics.get('trades', 0))}/"
                f"{_format_pf(split_metrics.get('profit_factor_normalized'))}"
            )
        lines.append(
            "| "
            f"{candidate.get('description', candidate.get('key', 'UNKNOWN'))} | "
            f"{split_cells[0]} | {split_cells[1]} | {split_cells[2]} | "
            f"{candidate.get('verdict', 'UNKNOWN')} |"
        )
    return lines


def write_lab_outputs(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "pnl_improvement_lab.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    truth = report["truth"]
    validation = report["temporal_validation"]
    findings = report["findings"]
    lines = [
        "# Laboratoire d'amelioration PnL HyperSmart",
        "",
        f"- Genere : `{report['generated_at']}`",
        "- Source : ledgers paper canoniques locaux, sessions actives et archivees",
        "- Reseau : non utilise",
        "- Activation automatique : **non**",
        "",
        "## Verite PnL",
        "",
        f"- Tous les round-trips apparies : {_markdown_metrics(truth['all_paired'])}.",
        f"- Echantillon eligible pour apprendre : {_markdown_metrics(truth['eligible_for_learning'])}.",
        "",
        "## Qualite des preuves",
        "",
        f"- Ledgers canoniques lus : `{report['quality'].get('ledger_files', 0)}`.",
        f"- Ouvertures / fermetures : `{report['quality'].get('open_events', 0)}` / "
        f"`{report['quality'].get('close_events', 0)}`.",
        f"- Round-trips apparies / eligibles : `{report['quality'].get('paired_round_trips', 0)}` / "
        f"`{report['quality'].get('eligible_round_trips', 0)}`.",
        f"- Fermetures orphelines / positions encore ouvertes : "
        f"`{report['quality'].get('orphan_closes', 0)}` / "
        f"`{report['quality'].get('still_open', 0)}`.",
        f"- Evenements non monotones / erreurs JSON : "
        f"`{report['quality'].get('non_monotonic_events', 0)}` / "
        f"`{report['quality'].get('json_errors', 0)}`.",
        f"- Exclusions : `{report['quality'].get('exclusion_reasons', {})}`.",
        "",
    ]
    groups = report.get("groups", {})
    eligible_truth = truth["eligible_for_learning"]
    lines.extend(
        [
            "## Causes mesurees",
            "",
            (
                "- Drag de frais sur le brut absolu : "
                f"`{float(eligible_truth.get('fee_drag_over_abs_gross') or 0.0):.1%}`."
            ),
            "- Les tableaux suivants sont descriptifs. Ils ne suffisent jamais a activer une regle.",
            "",
        ]
    )
    lines.extend(_group_table("Attribution par methode de sortie", groups.get("by_exit_method", [])))
    lines.extend([""])
    lines.extend(_group_table("Attribution par sens", groups.get("by_side", [])))
    lines.extend([""])
    lines.extend(
        _group_table(
            "Strategies les plus couteuses",
            groups.get("by_strategy", []),
            minimum_trades=2,
            limit=8,
        )
    )
    lines.extend([""])
    lines.extend(
        _group_table(
            "Coins recurrents les plus couteux",
            groups.get("by_coin", []),
            minimum_trades=2,
            limit=8,
        )
    )
    lines.extend([""])
    lines.extend(
        _group_table(
            "Coins recurrents les moins mauvais ou positifs",
            groups.get("by_coin", []),
            minimum_trades=2,
            limit=8,
            reverse=True,
        )
    )
    lines.extend(
        [
            "",
            "Les rangs par coin et strategie restent exploratoires : ils doivent etre "
            "confirmes hors echantillon avec frais et notionnel constants.",
            "",
            "## Validation temporelle",
            "",
            f"- Statut : `{validation.get('status')}`",
            f"- Split : `{validation.get('split', {})}`",
            f"- Holdout utilise pour selectionner : `{validation.get('selection_uses_holdout', False)}`",
            f"- Avertissement : {validation.get('multiple_testing_warning', validation.get('reason', ''))}",
            "",
            "### Matrice des hypotheses",
            "",
        ]
    )
    lines.extend(_candidate_table(validation.get("candidates", [])))
    lines.extend(
        [
            "",
            "## Pistes robustes",
            "",
        ]
    )
    robust = findings["robust_opportunities"]
    lines.extend(f"- {item}" for item in robust)
    if not robust:
        lines.append("- Aucune piste n'a encore passe train + validation + holdout.")
    lines.extend(["", "## Pistes a confirmer", ""])
    lines.extend(f"- {item}" for item in findings["needs_confirmation"])
    if not findings["needs_confirmation"]:
        lines.append("- Aucune piste selectionnee avec holdout insuffisant.")
    lines.extend(["", "## Hypotheses rejetees", ""])
    lines.extend(f"- {item}" for item in findings["rejected_hypotheses"])
    if not findings["rejected_hypotheses"]:
        lines.append("- Aucune hypothese rejetee enregistrable.")
    lines.extend(["", "## Donnees manquantes", ""])
    lines.extend(f"- {item}" for item in findings["missing_evidence"])
    if not findings["missing_evidence"]:
        lines.append("- Couverture suffisante sur les champs controles.")
    lines.extend(["", "## Prochains A/B exacts", ""])
    lines.extend(f"- {item}" for item in findings["next_exact_ab_experiments"])
    lines.extend(["", "## Backlog d'experiences priorise", ""])
    backlog = report.get("experiment_backlog", [])
    if isinstance(backlog, list) and backlog:
        for experiment in backlog:
            if not isinstance(experiment, dict):
                continue
            lines.extend(
                [
                    (
                        f"### P{experiment.get('priority')} - "
                        f"{experiment.get('title', experiment.get('experiment_id'))}"
                    ),
                    "",
                    f"- Identifiant : `{experiment.get('experiment_id')}`",
                    f"- Hypothese : {experiment.get('hypothesis')}",
                    (
                        "- Grille : `"
                        f"{json.dumps(experiment.get('parameter_grid', {}), ensure_ascii=False)}"
                        "`"
                    ),
                    (
                        "- Preuves requises : "
                        + ", ".join(
                            str(value)
                            for value in experiment.get("required_evidence", [])
                        )
                        + "."
                    ),
                    f"- Validation : {experiment.get('validation_protocol')}",
                    "- Activation automatique : **non**",
                    "",
                ]
            )
    else:
        lines.extend(
            [
                "- Aucun experiment exploitable tant que les donnees restent insuffisantes.",
                "",
            ]
        )
    lines.extend(
        [
            "## Regle de promotion",
            "",
            "Aucun flag n'est active par ce rapport. Une piste doit garder un PF net > 1 "
            "sur validation et holdout chronologiques, puis survivre au replay exact avec "
            "frais, spread, slippage et latence.",
            "",
            "**Un resultat historique ne garantit jamais un profit futur.**",
            "",
        ]
    )
    markdown_path = output_dir / "PNL_IMPROVEMENT_LAB.md"
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, markdown_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Autopsie historique et recherche PnL sans lookahead sur ledgers locaux."
    )
    parser.add_argument("--logs-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--comparison-notional",
        type=float,
        default=DEFAULT_COMPARISON_NOTIONAL_USDT,
    )
    parser.add_argument("--min-trades", type=int, default=MIN_TOTAL_TRADES)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    comparison_notional = max(1.0, float(args.comparison_notional))
    report = build_lab_report(
        Path(args.logs_dir),
        comparison_notional_usdt=comparison_notional,
        min_total_trades=max(12, int(args.min_trades)),
    )
    json_path, markdown_path = write_lab_outputs(report, Path(args.output_dir))
    truth = report["truth"]["eligible_for_learning"]
    print(
        "pnl_lab="
        f"trades:{truth['trades']} net:{truth['net_pnl_actual_usdc']:.6f} "
        f"pf:{truth['profit_factor_actual']} status:{report['temporal_validation']['status']}"
    )
    print(f"pnl_lab_json={json_path}")
    print(f"pnl_lab_markdown={markdown_path}")
    print("automatic_activation=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CANONICAL_LEDGER_NAME",
    "DEFAULT_COMPARISON_NOTIONAL_USDT",
    "HistoricalTrade",
    "RuleSpec",
    "build_candidate_rules",
    "build_lab_report",
    "compute_metrics",
    "compare_regime_ablation",
    "compare_copy_vault_liquidity_veto",
    "discover_session_ledgers",
    "evaluate_candidate_rules",
    "extract_historical_trades",
    "learn_train_only_markout_filter",
    "rank_correction_bottlenecks",
    "main",
    "rule_matches",
    "write_lab_outputs",
]
