from __future__ import annotations

import bisect
import ctypes
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"C:\Users\flo\Desktop\Projet invest")
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting import copy_vault_executable
from hl_observer.backtesting.copy_vault_execution_math import (
    _book_side,
    _walk_base_quantity,
)
from hl_observer.backtesting.copy_vault_protocol import COPY_DELAY_MS, MAX_TARGET_LAG_MS
from hl_observer.backtesting.copy_vault_v4_train import assess_train_variant
from hl_observer.backtesting.copy_vault_v5_lifecycle_train import replay_lifecycle_train
from hl_observer.backtesting.copy_vault_v6_balanced_train import (
    apply_causal_daily_risk_budget,
)
from hl_observer.backtesting.copy_vault_v8_entry_efficiency_train import (
    select_entry_efficiency,
)

STOP_LOSS_BPS = (10.0, 20.0, 40.0, 60.0)
TAKE_PROFIT_BPS = (20.0, 40.0, 80.0, 120.0)
KEEP_FRACTIONS = (0.25, 0.40, 0.50, 0.65)
VAULT_DAILY_LIMITS = (1, 2)
COIN_DAILY_LIMIT = 1
TRIAL_COUNT = 240
HORIZON_MS = 3_600_000
FEE_BPS = 4.5


def load_pipeline():
    path = ROOT / "tools" / "pipeline_copie_reel.py"
    spec = importlib.util.spec_from_file_location("copy_v10_risk_pipeline", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def executable_net_bps(trade: dict, book: dict) -> float | None:
    direction = int(trade["direction"])
    top = float(book["bid"] if direction > 0 else book["ask"])
    levels = _book_side(
        book,
        "bids5" if direction > 0 else "asks5",
        expected_best=top,
        descending=direction > 0,
    )
    if levels is None:
        return None
    exit_price = _walk_base_quantity(levels, float(trade["quantity"]))
    if exit_price is None:
        return None
    quantity = float(trade["quantity"])
    entry_price = float(trade["entry_price"])
    fees = (
        abs(quantity * entry_price) + abs(quantity * exit_price)
    ) * FEE_BPS / 10_000.0
    net = quantity * direction * (exit_price - entry_price) - fees
    return net / float(trade["notional_usd"]) * 10_000.0


def apply_risk_exit(
    trade: dict,
    metaorder: dict,
    books: list[dict],
    timestamps: list[int],
    *,
    stop_loss_bps: float,
    take_profit_bps: float,
) -> tuple[dict, str]:
    entry_ms = int(trade["entry_ts_ms"])
    fallback_exit_ms = int(trade["exit_ts_ms"])
    start = bisect.bisect_right(timestamps, entry_ms)
    end = bisect.bisect_right(timestamps, fallback_exit_ms)
    trigger_book = None
    trigger = None
    for book in books[start:end]:
        net_bps = executable_net_bps(trade, book)
        if net_bps is None:
            continue
        if net_bps <= -abs(stop_loss_bps):
            trigger_book = book
            trigger = "EXECUTABLE_NET_STOP"
            break
        if net_bps >= abs(take_profit_bps):
            trigger_book = book
            trigger = "EXECUTABLE_NET_TAKE_PROFIT"
            break
    if trigger_book is None:
        return {
            **trade,
            "risk_exit_policy": "FIRST_EXECUTABLE_NET_STOP_OR_TAKE_PROFIT",
            "risk_stop_loss_bps": stop_loss_bps,
            "risk_take_profit_bps": take_profit_bps,
            "risk_exit_trigger": "LIFECYCLE_FALLBACK",
        }, "LIFECYCLE_FALLBACK"
    direction_multiplier = (
        1
        if int(trade["direction"]) == int(metaorder["direction"])
        else -1
    )
    dynamic_horizon = int(trigger_book["ts_ms"]) - entry_ms
    adjusted, reason = copy_vault_executable.execute_metaorder(
        metaorder,
        books,
        horizon_ms=dynamic_horizon,
        direction_multiplier=direction_multiplier,
        notional_usd=float(trade["notional_usd"]),
        require_causal_books=True,
    )
    if adjusted is None:
        return {
            **trade,
            "risk_exit_policy": "FIRST_EXECUTABLE_NET_STOP_OR_TAKE_PROFIT",
            "risk_stop_loss_bps": stop_loss_bps,
            "risk_take_profit_bps": take_profit_bps,
            "risk_exit_trigger": "RECONSTRUCTION_REFUSED_FALLBACK",
            "risk_exit_reconstruction_reason": reason,
        }, "RECONSTRUCTION_REFUSED_FALLBACK"
    return {
        **adjusted,
        "mechanism": "copy_vault_v10_causal_executable_risk_exits",
        "walk_forward_segment": "train",
        "required_observed_fills": 2,
        "max_hold_ms": HORIZON_MS,
        "exit_policy": "FIRST_RISK_TRIGGER_ELSE_LEADER_EXIT_ELSE_TIME_STOP",
        "exit_trigger": trigger,
        "risk_exit_policy": "FIRST_EXECUTABLE_NET_STOP_OR_TAKE_PROFIT",
        "risk_stop_loss_bps": stop_loss_bps,
        "risk_take_profit_bps": take_profit_bps,
        "risk_exit_trigger": trigger,
        "paper_read_only": True,
        "real_execution": False,
    }, trigger


def adjust_all(
    trades: list[dict],
    continuation_by_id: dict[str, dict],
    books: dict[str, list[dict]],
    timestamps: dict[str, list[int]],
    *,
    stop_loss_bps: float,
    take_profit_bps: float,
) -> tuple[list[dict], dict[str, int]]:
    result = []
    audit: dict[str, int] = defaultdict(int)
    for trade in trades:
        metaorder = continuation_by_id.get(str(trade.get("metaorder_id")))
        coin = str(trade.get("coin") or "").upper()
        if metaorder is None or coin not in books:
            audit["MISSING_CAUSAL_INPUT_FALLBACK"] += 1
            result.append(dict(trade))
            continue
        adjusted, trigger = apply_risk_exit(
            dict(trade),
            metaorder,
            books[coin],
            timestamps[coin],
            stop_loss_bps=stop_loss_bps,
            take_profit_bps=take_profit_bps,
        )
        result.append(adjusted)
        audit[trigger] += 1
    result.sort(key=lambda row: (int(row["entry_ts_ms"]), str(row["trade_id"])))
    return result, dict(audit)


def mean_daily(statistics: dict) -> float | None:
    values = list(statistics.get("daily_net_pnl_usd") or ())
    return sum(values) / len(values) if values else None


def main() -> None:
    ctypes.windll.kernel32.SetPriorityClass(
        ctypes.windll.kernel32.GetCurrentProcess(), 0x40
    )
    pipeline = load_pipeline()
    entries, entries_audit = pipeline.charger_entrees_alpha_notional_fixe_avec_audit(ROOT)
    meta_all, meta_audit = copy_vault_executable.cluster_metaorders(entries)
    books_all, books_audit = copy_vault_executable.load_observed_books(
        ROOT, coins={row["coin"] for row in meta_all}
    )
    meta, causal_books, protocol_audit = (
        copy_vault_executable.select_causal_protocol_inputs(
            meta_all, books_all
        )
    )
    events, events_audit = pipeline.charger_evenements_lifecycle_avec_audit(ROOT)
    continuations, continuation_audit = (
        copy_vault_executable.select_observed_continuations(
            meta, required_observed_fills=2
        )
    )
    bounds = copy_vault_executable.temporal_bounds(
        continuations,
        purge_ms=COPY_DELAY_MS + HORIZON_MS + MAX_TARGET_LAG_MS,
    )
    train_start = int(bounds["train_start_ms"])
    train_end = int(bounds["train_end_ms"])
    parent, parent_audit = replay_lifecycle_train(
        meta,
        causal_books,
        events,
        required_observed_fills=2,
        horizon_ms=HORIZON_MS,
        train_start_ms=train_start,
        train_end_ms=train_end,
    )
    placebo_parent, placebo_parent_audit = replay_lifecycle_train(
        meta,
        causal_books,
        events,
        required_observed_fills=2,
        horizon_ms=HORIZON_MS,
        train_start_ms=train_start,
        train_end_ms=train_end,
        direction_multiplier=-1,
    )
    continuation_by_id = {
        str(row["metaorder_id"]): row for row in continuations
    }
    continuous_books = {
        coin: [
            dict(row)
            for row in rows
            if row.get("causal_observation") is True
            and not row.get("checkpoint_id")
        ]
        for coin, rows in causal_books.items()
    }
    for rows in continuous_books.values():
        rows.sort(key=lambda row: int(row["ts_ms"]))
    timestamps = {
        coin: [int(row["ts_ms"]) for row in rows]
        for coin, rows in continuous_books.items()
    }

    variants = []
    for stop in STOP_LOSS_BPS:
        for take_profit in TAKE_PROFIT_BPS:
            adjusted, risk_audit = adjust_all(
                parent,
                continuation_by_id,
                continuous_books,
                timestamps,
                stop_loss_bps=stop,
                take_profit_bps=take_profit,
            )
            placebo_adjusted, placebo_risk_audit = adjust_all(
                placebo_parent,
                continuation_by_id,
                continuous_books,
                timestamps,
                stop_loss_bps=stop,
                take_profit_bps=take_profit,
            )
            for keep_fraction in KEEP_FRACTIONS:
                efficient, efficiency_audit = select_entry_efficiency(
                    adjusted, keep_fraction=keep_fraction
                )
                for vault_limit in VAULT_DAILY_LIMITS:
                    admitted, budget_audit = apply_causal_daily_risk_budget(
                        efficient,
                        max_entries_per_vault_day=vault_limit,
                        max_entries_per_coin_day=COIN_DAILY_LIMIT,
                    )
                    admitted_ids = {
                        str(row["metaorder_id"])
                        for row in admitted
                    }
                    placebo_admitted = [
                        row
                        for row in placebo_adjusted
                        if str(row.get("metaorder_id")) in admitted_ids
                    ]
                    assessment = assess_train_variant(
                        admitted,
                        placebo_admitted,
                        trial_count=TRIAL_COUNT,
                    )
                    daily = mean_daily(assessment["statistics"])
                    reasons = list(assessment["reasons"])
                    if daily is None or daily < 4.0:
                        reasons.append("DAILY_MEAN_NET_BELOW_4_USD")
                    variants.append(
                        {
                            "stop_loss_bps": stop,
                            "take_profit_bps": take_profit,
                            "entry_efficiency_keep_fraction": keep_fraction,
                            "max_entries_per_vault_day": vault_limit,
                            "max_entries_per_coin_day": COIN_DAILY_LIMIT,
                            **assessment,
                            "eligible": not reasons,
                            "reasons": reasons,
                            "daily_mean_net_pnl_usd": daily,
                            "risk_exit_audit": risk_audit,
                            "placebo_risk_exit_audit": placebo_risk_audit,
                            "entry_efficiency_audit": efficiency_audit,
                            "budget_audit": budget_audit,
                            "trades": admitted,
                        }
                    )
    eligible = [row for row in variants if row["eligible"]]
    selected = max(
        eligible,
        key=lambda row: (
            float(row["statistics"].get("total_lcb_usd") or 0),
            float(row["statistics"].get("net_pnl_usd") or 0),
        ),
        default=None,
    )
    best = max(
        variants,
        key=lambda row: float(row["statistics"].get("net_pnl_usd") or 0),
        default=None,
    )
    def compact(row: dict | None) -> dict | None:
        if row is None:
            return None
        return {key: value for key, value in row.items() if key != "trades"}

    report = {
        "schema_version": "hypersmart.copy_vault_v10_causal_risk_exits_train.v1",
        "mechanism": "copy_vault_v10_causal_executable_risk_exits",
        "status": "TRAIN_ELIGIBLE_TO_FREEZE" if selected else "NO_ROBUST_TRAIN_CANDIDATE",
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_evaluated": False,
        "bounds": bounds,
        "input_audit": {
            "entries": entries_audit,
            "metaorders": meta_audit,
            "books": books_audit,
            "protocol": protocol_audit,
            "events": events_audit,
            "continuations": continuation_audit,
            "parent": parent_audit,
            "placebo_parent": placebo_parent_audit,
        },
        "fixed_grid": {
            "stop_loss_bps": STOP_LOSS_BPS,
            "take_profit_bps": TAKE_PROFIT_BPS,
            "entry_efficiency_keep_fraction": KEEP_FRACTIONS,
            "max_entries_per_vault_day": VAULT_DAILY_LIMITS,
            "max_entries_per_coin_day": COIN_DAILY_LIMIT,
            "trial_count": TRIAL_COUNT,
        },
        "selected": selected,
        "diagnostic_best": compact(best),
        "variant_summaries": [compact(row) for row in variants],
        "paper_read_only": True,
        "real_execution": False,
    }
    output = (
        ROOT
        / "runtime/reports/economic_campaigns/research_vnext"
        / "copy_vault_v10_causal_risk_exits_train.json"
    )
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "status": report["status"],
                "selected": compact(selected),
                "diagnostic_best": compact(best),
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
