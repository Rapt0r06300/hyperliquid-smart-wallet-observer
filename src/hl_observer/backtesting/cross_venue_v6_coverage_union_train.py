"""Cross-Venue v6 TRAIN-only coverage union and broad universe replay.

The candidate universe and temporal boundary were frozen from certified
coverage before any v6 outcome replay.  This module never evaluates heldout
rows and remains paper/read-only.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting import cross_venue_v3_train as v3
from hl_observer.backtesting import cross_venue_v4_train as v4
from hl_observer.backtesting.cross_venue_certified import UNION_SOURCE_MODE
from hl_observer.backtesting.train_statistics import stable_hash, summarize_train_rows
from hl_observer.economics.assumptions import EconomicRunMode

SCHEMA_VERSION = "hypersmart.cross_venue_v6_coverage_union_train.v1"
MECHANISM = "cross_venue_v6_coverage_union_broad_universe"
TRAIN_START_MS = 1_787_416_361_565.5007
TRAIN_END_MS = 1_788_519_885_717.8003
MIN_TRAIN_ROWS = 500
MIN_TRAIN_DAYS = 3
PREDECLARED_COINS = (
    "ACE", "AR", "ATOM", "BSV", "DASH", "DOT", "FARTCOIN", "FET", "GMT",
    "HMSTR", "INJ", "JTO", "LINEA", "MON", "MORPHO", "MOVE", "NEO", "NIL",
    "POLYX", "RUNE", "VIRTUAL", "WLD", "XMR", "XPL", "YGG", "ZORA",
)
PRIOR_FAMILY_TRIAL_COUNT = 486
NEW_TRIAL_COUNT = len(PREDECLARED_COINS) * len(v4.TAKE_PROFIT_NET_BPS) * len(v4.STOP_LOSS_NET_BPS)
BONFERRONI_TRIAL_COUNT = PRIOR_FAMILY_TRIAL_COUNT + NEW_TRIAL_COUNT
MIN_DAILY_NET_USD = 4.0


def coverage_by_coin(
    series: Mapping[str, Sequence[Sequence[Any]]],
) -> dict[str, dict[str, Any]]:
    """Measure only predeclared TRAIN coverage; no price or outcome is inspected."""

    result: dict[str, dict[str, Any]] = {}
    for coin in PREDECLARED_COINS:
        timestamps = [
            float(row[0])
            for row in series.get(coin, ())
            if row and TRAIN_START_MS <= float(row[0]) <= TRAIN_END_MS
        ]
        days = sorted({int(timestamp) // 86_400_000 for timestamp in timestamps})
        result[coin] = {
            "train_rows": len(timestamps),
            "distinct_utc_days": len(days),
            "coverage_eligible": len(timestamps) >= MIN_TRAIN_ROWS and len(days) >= MIN_TRAIN_DAYS,
        }
    return result


def explore_cross_venue_v6_train(
    series: Mapping[str, Sequence[Sequence[Any]]],
    depth: Mapping[str, Sequence[tuple[float, float]]],
    *,
    source_mode: str,
    source_meta: Mapping[str, Any] | None = None,
    economic_mode: EconomicRunMode | str = EconomicRunMode.EXPLORATORY,
) -> dict[str, Any]:
    contract = v3.economic_contract(economic_mode)
    coverage = coverage_by_coin(series)
    eligible_coins = tuple(
        coin for coin in PREDECLARED_COINS if coverage[coin]["coverage_eligible"]
    )
    base = {
        "schema_version": SCHEMA_VERSION,
        "mechanism": MECHANISM,
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_evaluated": False,
        "source_mode": source_mode,
        "train_bounds": {"start_ms": TRAIN_START_MS, "end_ms": TRAIN_END_MS},
        "coverage": coverage,
        "predeclared_coins": list(PREDECLARED_COINS),
        "coverage_eligible_coins": list(eligible_coins),
        "economic_contract": contract.receipt(),
        "paper_read_only": True,
        "real_execution": False,
    }
    if (
        source_mode != UNION_SOURCE_MODE
        or not v3._normalization_proof_ok(source_mode, source_meta)
        or eligible_coins != PREDECLARED_COINS
    ):
        return {
            **base,
            "status": "PREDECLARED_CERTIFIED_COVERAGE_REQUIRED",
            "selection_eligible": False,
            "physical_freeze_allowed": False,
        }

    paths, path_diagnostics = v4._build_train_paths(
        series,
        depth,
        train_end_ms=TRAIN_END_MS,
        economic=contract,
        candidate_coins=PREDECLARED_COINS,
    )
    variants: list[dict[str, Any]] = []
    for take_profit in v4.TAKE_PROFIT_NET_BPS:
        for stop_loss in v4.STOP_LOSS_NET_BPS:
            trades, diagnostics = v4._settle_policy(
                paths,
                take_profit_net_bps=take_profit,
                stop_loss_net_bps=stop_loss,
            )
            statistics = summarize_train_rows(
                trades,
                value_key="net_pnl_usd",
                timestamp_key="entry_ts_ms",
                trial_count=BONFERRONI_TRIAL_COUNT,
                family_alpha=v4.FAMILY_ALPHA,
            )
            net = float(statistics.get("net_pnl_usd") or 0.0)
            days = int(statistics.get("distinct_days") or 0)
            daily_mean = net / days if days else None
            profit_factor = statistics.get("profit_factor")
            total_lcb = statistics.get("total_lcb_usd")
            placebo_net = v4._placebo_net(trades)
            eligible = bool(
                len(trades) >= v4.MIN_TRAIN_TRADES
                and days >= v4.MIN_DISTINCT_DAYS
                and daily_mean is not None
                and daily_mean >= MIN_DAILY_NET_USD
                and profit_factor is not None
                and float(profit_factor) > 1.0
                and total_lcb is not None
                and float(total_lcb) > 0.0
                and float(statistics.get("top_positive_trade_share") or 1.0)
                <= v4.MAX_TOP_POSITIVE_SHARE
                and net > placebo_net + 1e-12
            )
            variants.append({
                "take_profit_net_bps": take_profit,
                "stop_loss_net_bps": stop_loss,
                "statistics": {**statistics, "daily_mean_net_pnl_usd": daily_mean},
                "placebo_net_pnl_usd": placebo_net,
                "diagnostics": diagnostics,
                "eligible": eligible,
            })
    selected = max(
        (row for row in variants if row["eligible"]),
        key=lambda row: float(row["statistics"].get("total_lcb_usd") or 0.0),
        default=None,
    )
    diagnostic_best = max(
        variants,
        key=lambda row: float(row["statistics"].get("net_pnl_usd") or 0.0),
        default=None,
    )
    freeze_candidate = (
        {
            "mechanism": MECHANISM,
            "predeclared_coins": list(PREDECLARED_COINS),
            "train_end_ms": TRAIN_END_MS,
            "take_profit_net_bps": selected["take_profit_net_bps"],
            "stop_loss_net_bps": selected["stop_loss_net_bps"],
            "source_mode": source_mode,
        }
        if selected else None
    )
    return {
        **base,
        "status": "TRAIN_ELIGIBLE_TO_FREEZE" if selected else "NO_ROBUST_TRAIN_CANDIDATE",
        "selection_eligible": selected is not None,
        "physical_freeze_allowed": selected is not None,
        "fixed_grid": {
            "take_profit_net_bps": list(v4.TAKE_PROFIT_NET_BPS),
            "stop_loss_net_bps": list(v4.STOP_LOSS_NET_BPS),
            "prior_family_trial_count": PRIOR_FAMILY_TRIAL_COUNT,
            "new_trial_count": NEW_TRIAL_COUNT,
            "bonferroni_trial_count": BONFERRONI_TRIAL_COUNT,
            "minimum_daily_net_usd": MIN_DAILY_NET_USD,
        },
        "path_diagnostics": path_diagnostics,
        "selected": selected,
        "diagnostic_best_train_variant": diagnostic_best,
        "freeze_candidate": freeze_candidate,
        "freeze_candidate_sha256": stable_hash(freeze_candidate) if freeze_candidate else None,
        "variants": variants,
    }


__all__ = [
    "BONFERRONI_TRIAL_COUNT", "MECHANISM", "PREDECLARED_COINS", "SCHEMA_VERSION",
    "coverage_by_coin", "explore_cross_venue_v6_train",
]
