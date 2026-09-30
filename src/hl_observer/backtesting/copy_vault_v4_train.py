"""Copy-Vault V4 TRAIN-only: continuation causale à notional paper fixe.

La stratégie Copy-Vault historique exige un NAV observable afin de reproduire
un ratio de taille leader. Cette hypothèse distincte ne dépend pas du NAV : elle
attend plusieurs fills LIVE_WS causaux du même métaordre, puis engage le
notional paper fixe déjà défini par le protocole exécutable.

La sélection reste strictement TRAIN-only. Une grille finie et pré-déclarée
contrôle le nombre de fills observés et l'horizon. Les coûts, le prix exécutable
et le placebo inversé passent tous par le replay canonique. Ce module ne lit ni
validation, ni OOS, ni forward et ne peut pas certifier la famille.

PAPER/READ-ONLY. Aucun client d'ordre ou d'exchange n'est importé.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.copy_vault_executable import (
    replay_metaorders,
    select_observed_continuations,
    summarize,
    temporal_bounds,
)
from hl_observer.backtesting.copy_vault_protocol import (
    COPY_DELAY_MS,
    HORIZONS_MS,
    MAX_TARGET_LAG_MS,
    NOTIONAL_USD,
)
from hl_observer.backtesting.train_statistics import stable_hash, summarize_train_rows

SCHEMA_VERSION = "hypersmart.copy_vault_v4_train.v1"
MECHANISM = "copy_vault_v4_causal_observed_fill_continuation"
REQUIRED_OBSERVED_FILLS = (2, 3, 4, 5)
MIN_TRAIN_TRADES = 8
MIN_DISTINCT_DAYS = 3
MAX_COIN_TRADE_SHARE = 0.65
MAX_VAULT_TRADE_SHARE = 0.60
MAX_TOP_POSITIVE_SHARE = 0.60
FAMILY_ALPHA = 0.05


def _concentration(rows: Sequence[Mapping[str, Any]], field: str) -> float:
    counts = Counter(str(row.get(field) or "UNKNOWN") for row in rows)
    return max(counts.values(), default=0) / max(1, len(rows))


def replay_continuation_train(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    *,
    required_observed_fills: int,
    horizon_ms: int,
    train_start_ms: int | None,
    train_end_ms: int | None,
    direction_multiplier: int = 1,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rejoue une variante sur la seule fenêtre TRAIN fournie."""

    continuations, selection_audit = select_observed_continuations(
        metaorders,
        required_observed_fills=int(required_observed_fills),
    )
    if (
        train_start_ms is None
        or train_end_ms is None
        or int(train_end_ms) < int(train_start_ms)
    ):
        return [], {
            "selection": selection_audit,
            "replay": {
                "metaorders_considered": 0,
                "completed_positions": 0,
                "INVALID_OR_MISSING_TRAIN_BOUNDS": len(continuations),
            },
            "train_start_ms": train_start_ms,
            "train_end_ms": train_end_ms,
            "direction_multiplier": 1 if int(direction_multiplier) >= 0 else -1,
        }
    trades, replay_audit = replay_metaorders(
        continuations,
        books_by_coin,
        horizon_ms=int(horizon_ms),
        start_ms=train_start_ms,
        end_ms=train_end_ms,
        direction_multiplier=int(direction_multiplier),
        require_causal_observation=True,
    )
    annotated = [
        {
            **trade,
            "mechanism": MECHANISM,
            "walk_forward_segment": "train",
            "required_observed_fills": int(required_observed_fills),
            "continuation_horizon_ms": int(horizon_ms),
            "sizing_policy": "FIXED_PAPER_NOTIONAL_USD",
            "paper_read_only": True,
            "real_execution": False,
        }
        for trade in trades
    ]
    return annotated, {
        "selection": selection_audit,
        "replay": replay_audit,
        "train_start_ms": train_start_ms,
        "train_end_ms": train_end_ms,
        "direction_multiplier": 1 if int(direction_multiplier) >= 0 else -1,
    }


def assess_train_variant(
    trades: Sequence[Mapping[str, Any]],
    placebo_trades: Sequence[Mapping[str, Any]],
    *,
    trial_count: int,
) -> dict[str, Any]:
    """Applique les garde-fous économiques et statistiques pré-déclarés."""

    rows = [dict(row) for row in trades]
    placebo_rows = [dict(row) for row in placebo_trades]
    economic = summarize(rows)
    placebo = summarize(placebo_rows)
    statistics = summarize_train_rows(
        rows,
        value_key="net_pnl_usd",
        timestamp_key="entry_ts_ms",
        trial_count=int(trial_count),
        family_alpha=FAMILY_ALPHA,
    )
    coin_share = _concentration(rows, "coin")
    vault_share = _concentration(rows, "vault")
    net = float(statistics.get("net_pnl_usd") or 0.0)
    placebo_net = float(placebo.get("net_pnl_usd") or 0.0)
    profit_factor = statistics.get("profit_factor")
    total_lcb = statistics.get("total_lcb_usd")
    reasons: list[str] = []
    if len(rows) < MIN_TRAIN_TRADES:
        reasons.append("INSUFFICIENT_TRAIN_TRADES")
    if int(statistics.get("distinct_days") or 0) < MIN_DISTINCT_DAYS:
        reasons.append("INSUFFICIENT_DISTINCT_DAYS")
    if net <= 0.0:
        reasons.append("TRAIN_NET_NOT_POSITIVE")
    if profit_factor is None or float(profit_factor) <= 1.0:
        reasons.append("TRAIN_PROFIT_FACTOR_NOT_ABOVE_ONE")
    if total_lcb is None or float(total_lcb) <= 0.0:
        reasons.append("MULTIPLICITY_ADJUSTED_LCB_NOT_POSITIVE")
    if float(statistics.get("top_positive_trade_share") or 1.0) > MAX_TOP_POSITIVE_SHARE:
        reasons.append("TOP_POSITIVE_TRADE_CONCENTRATION_TOO_HIGH")
    if coin_share > MAX_COIN_TRADE_SHARE:
        reasons.append("COIN_TRADE_CONCENTRATION_TOO_HIGH")
    if vault_share > MAX_VAULT_TRADE_SHARE:
        reasons.append("VAULT_TRADE_CONCENTRATION_TOO_HIGH")
    if net <= placebo_net + 1e-12:
        reasons.append("PLACEBO_NOT_BEATEN")
    if economic.get("LIQUIDATABLE_NET") is not True:
        reasons.append("LIQUIDATABLE_NET_NOT_PROVEN")
    if economic.get("economic_reconciliation_ok") is not True:
        reasons.append("ECONOMIC_RECONCILIATION_FAILED")
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "statistics": statistics,
        "economic_summary": economic,
        "placebo_summary": placebo,
        "largest_coin_trade_share": coin_share,
        "largest_vault_trade_share": vault_share,
    }


def explore_copy_vault_v4_train(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    *,
    input_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Explore la famille finie N fills x horizons sans ouvrir les heldouts."""

    ordered = sorted(
        [dict(row) for row in metaorders],
        key=lambda row: (int(row.get("signal_ts_ms") or 0), str(row.get("metaorder_id") or "")),
    )
    grid = [
        (required, int(horizon))
        for required in REQUIRED_OBSERVED_FILLS
        for horizon in HORIZONS_MS
    ]
    trial_count = len(grid)
    variants: list[dict[str, Any]] = []
    continuation_cache: dict[int, tuple[list[dict[str, Any]], dict[str, Any]]] = {}
    for required, horizon in grid:
        if required not in continuation_cache:
            continuation_cache[required] = select_observed_continuations(
                ordered,
                required_observed_fills=required,
            )
        continuations, selection_audit = continuation_cache[required]
        purge_ms = COPY_DELAY_MS + int(horizon) + MAX_TARGET_LAG_MS
        bounds = temporal_bounds(continuations, purge_ms=purge_ms)
        train_start_ms = bounds.get("train_start_ms")
        train_end_ms = bounds.get("train_end_ms")
        valid_train_bounds = bool(
            train_start_ms is not None
            and train_end_ms is not None
            and int(train_end_ms) >= int(train_start_ms)
        )
        if valid_train_bounds:
            trades, replay_audit = replay_metaorders(
                continuations,
                books_by_coin,
                horizon_ms=int(horizon),
                start_ms=train_start_ms,
                end_ms=train_end_ms,
                require_causal_observation=True,
            )
            placebo_trades, placebo_audit = replay_metaorders(
                continuations,
                books_by_coin,
                horizon_ms=int(horizon),
                start_ms=train_start_ms,
                end_ms=train_end_ms,
                direction_multiplier=-1,
                require_causal_observation=True,
            )
        else:
            replay_audit = {
                "metaorders_considered": 0,
                "completed_positions": 0,
                "INVALID_OR_MISSING_TRAIN_BOUNDS": len(continuations),
            }
            placebo_audit = dict(replay_audit)
            trades = []
            placebo_trades = []
        annotated = [
            {
                **trade,
                "mechanism": MECHANISM,
                "walk_forward_segment": "train",
                "required_observed_fills": required,
                "continuation_horizon_ms": horizon,
                "sizing_policy": "FIXED_PAPER_NOTIONAL_USD",
            }
            for trade in trades
        ]
        assessment = assess_train_variant(
            annotated,
            placebo_trades,
            trial_count=trial_count,
        )
        variants.append(
            {
                "required_observed_fills": required,
                "horizon_ms": horizon,
                "bounds": bounds,
                "selection_audit": selection_audit,
                "replay_audit": replay_audit,
                "placebo_replay_audit": placebo_audit,
                **assessment,
            }
        )

    eligible_rows = [row for row in variants if row["eligible"]]
    selected = max(
        eligible_rows,
        key=lambda row: (
            float((row["statistics"] or {}).get("total_lcb_usd") or 0.0),
            float((row["statistics"] or {}).get("net_pnl_usd") or 0.0),
        ),
        default=None,
    )
    diagnostic_best = max(
        variants,
        key=lambda row: float((row["statistics"] or {}).get("net_pnl_usd") or 0.0),
        default=None,
    )
    freeze_candidate = (
        {
            "mechanism": MECHANISM,
            "required_observed_fills": selected["required_observed_fills"],
            "horizon_ms": selected["horizon_ms"],
            "copy_delay_ms": COPY_DELAY_MS,
            "notional_usd": NOTIONAL_USD,
            "sizing_policy": "FIXED_PAPER_NOTIONAL_USD",
            "nav_required": False,
            "causal_observation_required": True,
            "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        }
        if selected
        else None
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "mechanism": MECHANISM,
        "status": "TRAIN_ELIGIBLE_TO_FREEZE" if selected else "NO_ROBUST_TRAIN_CANDIDATE",
        "selection_eligible": selected is not None,
        "physical_freeze_allowed": selected is not None,
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_evaluated": False,
        "input_metaorders": len(ordered),
        "input_audit": dict(input_audit or {}),
        "fixed_grid": {
            "required_observed_fills": list(REQUIRED_OBSERVED_FILLS),
            "horizons_ms": [int(value) for value in HORIZONS_MS],
            "trial_count": trial_count,
        },
        "cost_contract": {
            "notional_usd": NOTIONAL_USD,
            "sizing_policy": "FIXED_PAPER_NOTIONAL_USD",
            "nav_required": False,
            "executable_bbo_entry_exit": True,
            "canonical_fees_spread_latency_capacity": True,
            "liquidatable_net_required": True,
        },
        "selected": selected,
        "diagnostic_best_train_variant": diagnostic_best,
        "freeze_candidate": freeze_candidate,
        "freeze_candidate_sha256": stable_hash(freeze_candidate) if freeze_candidate else None,
        "variants": variants,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "MECHANISM",
    "SCHEMA_VERSION",
    "assess_train_variant",
    "explore_copy_vault_v4_train",
    "replay_continuation_train",
]
